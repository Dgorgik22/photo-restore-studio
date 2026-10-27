using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

namespace PhotoRestoreSetup {
    public sealed class Asset { public string name {get;set;} public long bytes {get;set;} public string sha256 {get;set;} }
    public sealed class Release {
        public string version {get;set;} public long unpacked_bytes {get;set;}
        public List<Asset> archives {get;set;} public Dictionary<string,string> models {get;set;}
        public static Release Embedded() {
            using(var stream=typeof(Release).Assembly.GetManifestResourceStream("release.json"))
            using(var reader=new StreamReader(stream)) return new JavaScriptSerializer().Deserialize<Release>(reader.ReadToEnd());
        }
    }
    public sealed class Status {
        public string Phase; public int Percent,Part,Parts; public long Bytes,Total;
        public Status(string phase,int percent,int part=0,int parts=0,long bytes=0,long total=0) {
            Phase=phase;Percent=percent;Part=part;Parts=parts;Bytes=bytes;Total=total;
        }
    }
    public sealed class Options {
        public string Destination,SourceDirectory,CacheDirectory;
        public bool Shortcut=true,Compress=true,CleanDownloads=true;
    }
    public sealed class InstallerEngine:IDisposable {
        static InstallerEngine() {
            AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling",false);
            AppContext.SetSwitch("Switch.System.IO.BlockLongPaths",false);
        }
        public const string DownloadBase="https://github.com/Dgorgik22/photo-restore-studio/releases/download/v0.25.0-alpha-lite/";
        const string Marker="PhotoRestoreStudio Installer Cache v1";
        readonly Release release; readonly HttpClient client;readonly bool ownsClient;
        static string IOPath(string path) {
            path=Path.GetFullPath(path);
            return path.StartsWith(@"\\?\",StringComparison.Ordinal)?path:@"\\?\"+path;
        }
        static string DisplayPath(string path) {return path.StartsWith(@"\\?\",StringComparison.Ordinal)?path.Substring(4):path;}
        public InstallerEngine(Release manifest,HttpClient http=null) {
            release=manifest;
            ownsClient=http==null;
            client=http??new HttpClient(new HttpClientHandler {AllowAutoRedirect=true});
            client.Timeout=TimeSpan.FromHours(4);
            client.DefaultRequestHeaders.UserAgent.ParseAdd("PhotoRestoreStudio-Setup/0.25.1");
        }
        public void Dispose() {if(ownsClient) client.Dispose();}
        public static string Hash(string file,CancellationToken token) {
            using(var sha=SHA256.Create()) using(var input=File.OpenRead(IOPath(file))) {
                var buffer=new byte[1024*1024];int read;
                while((read=input.Read(buffer,0,buffer.Length))>0) {token.ThrowIfCancellationRequested();sha.TransformBlock(buffer,0,read,null,0);}
                sha.TransformFinalBlock(new byte[0],0,0);
                return BitConverter.ToString(sha.Hash).Replace("-","").ToLowerInvariant();
            }
        }
        static void RegularAncestors(string path) {
            var current=new DirectoryInfo(Path.GetFullPath(path));
            while(current!=null) {
                if(current.Exists&&(current.Attributes&FileAttributes.ReparsePoint)!=0) throw new IOException("LINKED_PATH");
                current=current.Parent;
            }
        }
        static void RegularFile(string path) {
            RegularAncestors(Path.GetDirectoryName(path));
            if(File.Exists(path)&&(File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0) throw new IOException("LINKED_PATH");
        }
        public static string ValidateDestination(string path) {
            path=Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar);
            if(path.StartsWith(@"\\")||path.Equals(Path.GetPathRoot(path).TrimEnd('\\'),StringComparison.OrdinalIgnoreCase)) throw new IOException("INVALID_DESTINATION");
            if(Directory.Exists(IOPath(path))||File.Exists(IOPath(path))) throw new IOException("DESTINATION_EXISTS");
            RegularAncestors(IOPath(path));return path;
        }
        bool Valid(string path,Asset item,CancellationToken token) {
            RegularFile(path);
            return File.Exists(path)&&new FileInfo(path).Length==item.bytes&&Hash(path,token)==item.sha256;
        }
        static void CheckSpace(Dictionary<string,long> required) {
            foreach(var row in required) {
                var drive=new DriveInfo(row.Key);
                if(drive.IsReady&&drive.AvailableFreeSpace<row.Value) throw new IOException("DISK_SPACE");
            }
        }
        static void AddSpace(Dictionary<string,long> required,string path,long size) {
            var root=Path.GetPathRoot(DisplayPath(Path.GetFullPath(path)));
            if(!required.ContainsKey(root)) required[root]=0;required[root]+=size;
        }
        public static string EntryDestination(string root,string name) {
            if(!name.StartsWith("PhotoRestoreStudio/",StringComparison.Ordinal)) throw new IOException("INVALID_ARCHIVE");
            var relative=name.Substring("PhotoRestoreStudio/".Length).Replace('/',Path.DirectorySeparatorChar);
            if(relative.IndexOf(':')>=0||Path.IsPathRooted(relative)||relative.Split('\\').Any(x=>x==".."||x==".")) throw new IOException("INVALID_ARCHIVE");
            var target=Path.GetFullPath(Path.Combine(root,relative));
            var prefix=Path.GetFullPath(root).TrimEnd('\\')+"\\";
            if(!target.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)) throw new IOException("INVALID_ARCHIVE");
            return target;
        }
        public async Task Download(Asset item,string file,Action<Status> report,int part,int parts,CancellationToken token) {
            var partial=file+".part";RegularFile(partial);RegularFile(file);
            for(int attempt=0;attempt<2;attempt++) {
                long existing=File.Exists(partial)?new FileInfo(partial).Length:0;
                if(existing>item.bytes) {File.Delete(partial);existing=0;}
                if(existing<item.bytes) {
                    using(var request=new HttpRequestMessage(HttpMethod.Get,DownloadBase+Uri.EscapeDataString(item.name))) {
                        if(existing>0) request.Headers.Range=new RangeHeaderValue(existing,null);
                        using(var response=await client.SendAsync(request,HttpCompletionOption.ResponseHeadersRead,token).ConfigureAwait(false)) {
                            response.EnsureSuccessStatusCode();
                            if(response.RequestMessage!=null&&response.RequestMessage.RequestUri.Scheme!="https") throw new IOException("INSECURE_DOWNLOAD");
                            bool append=existing>0&&response.StatusCode==HttpStatusCode.PartialContent;
                            if(append&&(response.Content.Headers.ContentRange==null||response.Content.Headers.ContentRange.From!=existing)) throw new IOException("INVALID_RANGE");
                            if(!append) existing=0;
                            long remaining=item.bytes-existing;
                            if(response.Content.Headers.ContentLength.HasValue&&response.Content.Headers.ContentLength.Value!=remaining) throw new IOException("DOWNLOAD_SIZE");
                            using(var registration=token.Register(()=>response.Dispose()))
                            using(var input=await response.Content.ReadAsStreamAsync().ConfigureAwait(false))
                            using(var output=new FileStream(partial,append?FileMode.Append:FileMode.Create,FileAccess.Write,FileShare.None,1024*1024,true)) {
                                var buffer=new byte[1024*1024];long done=existing;int read;var clock=Stopwatch.StartNew();long last=0;
                                while((read=await input.ReadAsync(buffer,0,buffer.Length,token).ConfigureAwait(false))>0) {
                                    token.ThrowIfCancellationRequested();done+=read;if(done>item.bytes) throw new IOException("DOWNLOAD_SIZE");
                                    await output.WriteAsync(buffer,0,read,token).ConfigureAwait(false);
                                    if(clock.ElapsedMilliseconds-last>=200) {report(new Status("download",5+(int)(50.0*((part-1)+(double)done/item.bytes)/parts),part,parts,done,item.bytes));last=clock.ElapsedMilliseconds;}
                                }
                                if(done!=item.bytes) throw new IOException("DOWNLOAD_SIZE");
                            }
                        }
                    }
                }
                report(new Status("verify",5+(50*part/parts),part,parts));
                if(Valid(partial,item,token)) {if(File.Exists(file)) File.Delete(file);File.Move(partial,file);return;}
                File.Delete(partial);
            }
            throw new IOException("HASH_MISMATCH");
        }
        static void RemoveStage(string stage,string parent) {
            if(!Directory.Exists(stage)) return;
            var full=Path.GetFullPath(stage);var expected=Path.GetFullPath(parent).TrimEnd('\\')+"\\";
            if(!full.StartsWith(expected,StringComparison.OrdinalIgnoreCase)||!Path.GetFileName(full).StartsWith("PhotoRestore-install-",StringComparison.Ordinal)) throw new IOException("INVALID_STAGE");
            RegularAncestors(full);
            CheckTree(full);
            Directory.Delete(full,true);
        }
        static void CheckTree(string root) {
            foreach(var entry in Directory.EnumerateFileSystemEntries(root)) {
                var attributes=File.GetAttributes(entry);
                if((attributes&FileAttributes.ReparsePoint)!=0) throw new IOException("LINKED_PATH");
                if((attributes&FileAttributes.Directory)!=0) CheckTree(entry);
            }
        }
        static void Compress(string folder,CancellationToken token) {
            if(!Directory.Exists(folder)) return;
            var start=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"compact.exe"),
                "/C /F /S:\""+folder+"\" /EXE:LZX /I /Q") {UseShellExecute=false,CreateNoWindow=true};
            using(var process=Process.Start(start)) {
                while(!process.WaitForExit(200)) if(token.IsCancellationRequested) {process.Kill();process.WaitForExit();token.ThrowIfCancellationRequested();}
                // Unsupported filesystems remain usable without NTFS compression.
            }
        }
        static void Shortcut(string target) {
            object shell=null,link=null;
            try {
                var type=Type.GetTypeFromProgID("WScript.Shell");shell=Activator.CreateInstance(type);
                var desktop=Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                var path=Path.Combine(desktop,"Photo Restore Studio Alpha.lnk");
                link=type.InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[]{path});
                var lt=link.GetType();
                foreach(var pair in new Dictionary<string,string>{{"TargetPath",Path.Combine(target,"PhotoRestoreStudio.exe")},{"WorkingDirectory",target},{"IconLocation",Path.Combine(target,"PhotoRestoreStudio.exe")+",0"}})
                    lt.InvokeMember(pair.Key,BindingFlags.SetProperty,null,link,new object[]{pair.Value});
                lt.InvokeMember("Save",BindingFlags.InvokeMethod,null,link,null);
            } finally {
                if(link!=null) System.Runtime.InteropServices.Marshal.FinalReleaseComObject(link);
                if(shell!=null) System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
            }
        }
        public async Task<string> Run(Options options,Action<Status> report,CancellationToken token) {
            string target=IOPath(ValidateDestination(options.Destination));
            string cache=IOPath(options.CacheDirectory),parent=Path.GetDirectoryName(target);
            if(cache.Equals(target,StringComparison.OrdinalIgnoreCase)||cache.StartsWith(target+"\\",StringComparison.OrdinalIgnoreCase)||target.StartsWith(cache+"\\",StringComparison.OrdinalIgnoreCase)) throw new IOException("INVALID_DESTINATION");
            RegularAncestors(cache);Directory.CreateDirectory(cache);
            var marker=Path.Combine(cache,".managed-installer");RegularFile(marker);
            if(File.Exists(marker)) {if(File.ReadAllText(marker)!=Marker) throw new IOException("INVALID_CACHE");}
            else {if(Directory.EnumerateFileSystemEntries(cache).Any()) throw new IOException("INVALID_CACHE");File.WriteAllText(marker,Marker);}
            var lockPath=Path.Combine(cache,"install.lock");RegularFile(lockPath);
            using(var cacheLock=new FileStream(lockPath,FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None)) {
                report(new Status("prepare",1));
                var resolved=new List<string>();var owned=new List<string>();long missing=0;
                for(int i=0;i<release.archives.Count;i++) {
                    token.ThrowIfCancellationRequested();var item=release.archives[i];
                    if(Path.GetFileName(item.name)!=item.name||item.bytes<=0||item.sha256==null||item.sha256.Length!=64) throw new IOException("INVALID_MANIFEST");
                    report(new Status("verify",2,i+1,release.archives.Count));
                    var adjacent=Path.Combine(IOPath(options.SourceDirectory),item.name);var cached=Path.Combine(cache,item.name);
                    if(Valid(adjacent,item,token)) resolved.Add(adjacent);
                    else if(Valid(cached,item,token)) {resolved.Add(cached);owned.Add(cached);}
                    else {resolved.Add(null);missing+=item.bytes;}
                }
                var required=new Dictionary<string,long>(StringComparer.OrdinalIgnoreCase);
                AddSpace(required,target,release.unpacked_bytes+256L*1024*1024);AddSpace(required,cache,missing+64L*1024*1024);CheckSpace(required);
                for(int i=0;i<resolved.Count;i++) if(resolved[i]==null) {
                    var cached=Path.Combine(cache,release.archives[i].name);
                    await Download(release.archives[i],cached,report,i+1,resolved.Count,token).ConfigureAwait(false);
                    resolved[i]=cached;owned.Add(cached);
                }
                token.ThrowIfCancellationRequested();Directory.CreateDirectory(parent);RegularAncestors(parent);
                var stage=Path.Combine(parent,"PhotoRestore-install-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(stage);
                bool committed=false;long expanded=0;
                try {
                    var buffer=new byte[1024*1024];
                    for(int i=0;i<resolved.Count;i++) using(var zip=ZipFile.OpenRead(resolved[i])) foreach(var entry in zip.Entries) {
                        token.ThrowIfCancellationRequested();
                        if(entry.FullName=="PhotoRestoreStudio/") continue;
                        var path=EntryDestination(stage,entry.FullName);
                        if(((entry.ExternalAttributes>>16)&0xf000)==0xa000) throw new IOException("INVALID_ARCHIVE");
                        if(entry.FullName.EndsWith("/")) {Directory.CreateDirectory(path);continue;}
                        expanded+=entry.Length;if(expanded>release.unpacked_bytes+1024*1024) throw new IOException("INVALID_ARCHIVE");
                        Directory.CreateDirectory(Path.GetDirectoryName(path));
                        using(var source=entry.Open()) using(var output=new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.None)) {
                            int read;while((read=source.Read(buffer,0,buffer.Length))>0) {token.ThrowIfCancellationRequested();output.Write(buffer,0,read);}
                        }
                        report(new Status("extract",55+(int)(30.0*expanded/Math.Max(1,release.unpacked_bytes)),i+1,resolved.Count));
                    }
                    if(!File.Exists(Path.Combine(stage,"PhotoRestoreStudio.exe"))) throw new IOException("INVALID_ARCHIVE");
                    report(new Status("models",86));
                    foreach(var model in release.models) {
                        var path=EntryDestination(stage,"PhotoRestoreStudio/"+model.Key.Replace('\\','/'));
                        if(!File.Exists(path)||Hash(path,token)!=model.Value) throw new IOException("HASH_MISMATCH");
                    }
                    if(options.Compress) {report(new Status("compress",90));Compress(Path.Combine(stage,"libraries"),token);Compress(Path.Combine(stage,"plugins"),token);}
                    token.ThrowIfCancellationRequested();RegularAncestors(target);
                    if(Directory.Exists(target)||File.Exists(target)) throw new IOException("DESTINATION_EXISTS");
                    Directory.Move(stage,target);committed=true;
                } finally {if(!committed) RemoveStage(stage,parent);}
                string warning=null;
                if(options.Shortcut) {try{Shortcut(DisplayPath(target));}catch{warning="shortcut";}}
                if(options.CleanDownloads) foreach(var file in owned) {try{RegularFile(file);File.Delete(file);}catch{warning="cleanup";}}
                report(new Status(warning==null?"done":warning,100));return DisplayPath(target);
            }
        }
    }
}
