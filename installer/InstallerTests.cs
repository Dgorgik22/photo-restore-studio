using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using PhotoRestoreSetup;
[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8",FrameworkDisplayName=".NET Framework 4.8")]

sealed class FakeHttp:HttpMessageHandler {
    public byte[] Data;public bool IgnoreRange;public long? RangeFrom;public int Calls;
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken token) {
        Calls++;RangeFrom=request.Headers.Range==null?null:request.Headers.Range.Ranges.First().From;
        long start=RangeFrom.HasValue&&!IgnoreRange?RangeFrom.Value:0;
        var response=new HttpResponseMessage(start>0?HttpStatusCode.PartialContent:HttpStatusCode.OK) {RequestMessage=request,Content=new ByteArrayContent(Data.Skip((int)start).ToArray())};
        if(start>0) response.Content.Headers.ContentRange=new ContentRangeHeaderValue(start,Data.Length-1,Data.Length);
        return Task.FromResult(response);
    }
}
static class Tests {
    static int passed;static string root;
    static void Check(bool value,string message) {if(!value) throw new Exception(message);}
    static void Test(string name,Action action) {action();passed++;Console.WriteLine("PASS "+name);}
    static string Folder(string name) {var p=Path.Combine(root,name);Directory.CreateDirectory(p);return p;}
    static byte[] Zip(string name,bool traversal=false) {
        var file=Path.Combine(Folder(name),"fixture.zip");
        using(var zip=ZipFile.Open(file,ZipArchiveMode.Create)) {
            var entry=zip.CreateEntry(traversal?"PhotoRestoreStudio/../../outside.txt":"PhotoRestoreStudio/PhotoRestoreStudio.exe");
            using(var writer=new StreamWriter(entry.Open())) writer.Write("test application fixture");
        }
        return File.ReadAllBytes(file);
    }
    static Asset Item(byte[] data,string directory) {
        var file=Path.Combine(directory,"fixture.zip");File.WriteAllBytes(file,data);
        return new Asset {name="fixture.zip",bytes=data.Length,sha256=InstallerEngine.Hash(file,CancellationToken.None)};
    }
    static Release Manifest(Asset a) {return new Release {version="test",archives=new List<Asset>{a},models=new Dictionary<string,string>(),unpacked_bytes=4096};}
    static Options Opt(string name) {return new Options {Destination=Path.Combine(root,name,"installed"),SourceDirectory=Folder(name+"-source"),CacheDirectory=Path.Combine(root,name,"cache"),Shortcut=false,Compress=false};}
    [STAThread] static int Main(string[] args) {
        root=Path.GetFullPath(args[0]);Directory.CreateDirectory(root);
        try {
            if(args.Length>1&&args[1]=="--network-probe") {
                var source=Path.Combine(Path.GetFullPath(args[2]),"README.md");
                var item=new Asset {name="README.md",bytes=new FileInfo(source).Length,sha256=InstallerEngine.Hash(source,CancellationToken.None)};
                new InstallerEngine(Release.Embedded()).Download(item,Path.Combine(root,"downloaded-readme.md"),s=>Console.WriteLine(s.Phase),1,1,CancellationToken.None).GetAwaiter().GetResult();
                Console.WriteLine("HTTPS DOWNLOAD AND SHA256 OK");return 0;
            }
            if(args.Length>1&&args[1]=="--real-install") {
                var options=new Options {Destination=Path.Combine(root,"installed"),SourceDirectory=Path.GetFullPath(args[2]),CacheDirectory=Path.Combine(root,"cache"),Shortcut=false,Compress=true};
                var result=new InstallerEngine(Release.Embedded()).Run(options,s=>{if(s.Phase!="extract")Console.WriteLine(s.Phase+" "+s.Percent);},CancellationToken.None).GetAwaiter().GetResult();
                Check(File.Exists(Path.Combine(result,"PhotoRestoreStudio.exe")),"Real executable missing");Console.WriteLine("REAL INSTALL OK "+result);return 0;
            }
            var data=Zip("original");var a=Item(data,Folder("hash"));
            Test("embedded manifest is pinned and contains four archives/five weights",()=>{var m=Release.Embedded();Check(m.archives.Count==4&&m.models.Count==5&&m.archives.All(x=>x.sha256.Length==64),"Invalid embedded release");});
            Test("offline installation reuses adjacent ZIP and never contacts network",()=>{var o=Opt("offline");File.WriteAllBytes(Path.Combine(o.SourceDirectory,a.name),data);var fake=new FakeHttp {Data=data};new InstallerEngine(Manifest(a),new HttpClient(fake)).Run(o,s=>{},CancellationToken.None).GetAwaiter().GetResult();Check(fake.Calls==0,"Network used");Check(File.Exists(Path.Combine(o.Destination,"PhotoRestoreStudio.exe")),"Install missing");});
            Test("long paths install without changing Windows settings",()=>{var o=Opt("long");o.Destination=Path.Combine(root,"long",new string('a',130),"installed");File.WriteAllBytes(Path.Combine(o.SourceDirectory,a.name),data);new InstallerEngine(Manifest(a)).Run(o,s=>{},CancellationToken.None).GetAwaiter().GetResult();Check(File.Exists(@"\\?\"+Path.Combine(o.Destination,"PhotoRestoreStudio.exe")),"Long-path installation missing");});
            Test("download resumes from partial data and cleans only owned downloads",()=>{var o=Opt("resume");Directory.CreateDirectory(o.CacheDirectory);File.WriteAllText(Path.Combine(o.CacheDirectory,".managed-installer"),"PhotoRestoreStudio Installer Cache v1");File.WriteAllBytes(Path.Combine(o.CacheDirectory,a.name+".part"),data.Take(17).ToArray());var fake=new FakeHttp {Data=data};new InstallerEngine(Manifest(a),new HttpClient(fake)).Run(o,s=>{},CancellationToken.None).GetAwaiter().GetResult();Check(fake.RangeFrom==17,"Range not sent");Check(!File.Exists(Path.Combine(o.CacheDirectory,a.name)),"Downloaded ZIP retained");});
            Test("server ignoring Range safely restarts without appending",()=>{var o=Opt("restart");Directory.CreateDirectory(o.CacheDirectory);File.WriteAllText(Path.Combine(o.CacheDirectory,".managed-installer"),"PhotoRestoreStudio Installer Cache v1");File.WriteAllBytes(Path.Combine(o.CacheDirectory,a.name+".part"),new byte[]{1,2,3});var fake=new FakeHttp {Data=data,IgnoreRange=true};new InstallerEngine(Manifest(a),new HttpClient(fake)).Run(o,s=>{},CancellationToken.None).GetAwaiter().GetResult();Check(fake.Calls==1,"Wrong request count");});
            Test("existing destination and user file are preserved",()=>{var o=Opt("existing");Directory.CreateDirectory(o.Destination);File.WriteAllText(Path.Combine(o.Destination,"user.txt"),"keep");try{new InstallerEngine(Manifest(a)).Run(o,s=>{},CancellationToken.None).GetAwaiter().GetResult();throw new Exception("Accepted existing folder");}catch(IOException ex){Check(ex.Message=="DESTINATION_EXISTS","Wrong error");}Check(File.ReadAllText(Path.Combine(o.Destination,"user.txt"))=="keep","User file changed");});
            Test("invalid ZIP traversal rolls back stage and cannot escape",()=>{var bad=Zip("traversal",true);var o=Opt("badzip");var item=Item(bad,o.SourceDirectory);try{new InstallerEngine(Manifest(item)).Run(o,s=>{},CancellationToken.None).GetAwaiter().GetResult();throw new Exception("Accepted traversal");}catch(IOException ex){Check(ex.Message=="INVALID_ARCHIVE","Wrong traversal error");}Check(!Directory.Exists(o.Destination)&&!File.Exists(Path.Combine(root,"outside.txt")),"Unsafe write");Check(!Directory.GetDirectories(Path.GetDirectoryName(o.Destination),"PhotoRestore-install-*").Any(),"Stage leaked");});
            Test("absolute paths and alternate data streams are rejected",()=>{foreach(var name in new[]{"PhotoRestoreStudio/C:/file","PhotoRestoreStudio/../file","PhotoRestoreStudio/a:stream","other/file"}) {try{InstallerEngine.EntryDestination(root,name);throw new Exception("Accepted "+name);}catch(IOException){}}});
            Test("cancellation before commit leaves no installation",()=>{var o=Opt("cancel");File.WriteAllBytes(Path.Combine(o.SourceDirectory,a.name),data);var cancel=new CancellationTokenSource();try{new InstallerEngine(Manifest(a)).Run(o,s=>{if(s.Phase=="verify")cancel.Cancel();},cancel.Token).GetAwaiter().GetResult();throw new Exception("Not cancelled");}catch(OperationCanceledException){}Check(!Directory.Exists(o.Destination),"Partial destination");});
            Test("corrupted download cannot install",()=>{var o=Opt("corrupt");var corrupted=(byte[])data.Clone();corrupted[20]^=1;try{new InstallerEngine(Manifest(a),new HttpClient(new FakeHttp {Data=corrupted})).Run(o,s=>{},CancellationToken.None).GetAwaiter().GetResult();throw new Exception("Bad checksum accepted");}catch(IOException ex){Check(ex.Message=="HASH_MISMATCH","Wrong checksum error");}Check(!Directory.Exists(o.Destination),"Corrupt installation");});
            Test("cancellation during extraction rolls back all staged files",()=>{var o=Opt("cancel-extract");File.WriteAllBytes(Path.Combine(o.SourceDirectory,a.name),data);var cancel=new CancellationTokenSource();try{new InstallerEngine(Manifest(a)).Run(o,s=>{if(s.Phase=="extract")cancel.Cancel();},cancel.Token).GetAwaiter().GetResult();throw new Exception("Not cancelled during extraction");}catch(OperationCanceledException){}Check(!Directory.Exists(o.Destination)&&!Directory.GetDirectories(Path.GetDirectoryName(o.Destination),"PhotoRestore-install-*").Any(),"Cancelled stage leaked");Check(File.Exists(Path.Combine(o.SourceDirectory,a.name)),"Offline source deleted");});
            Test("wrong model checksum rolls back installation",()=>{var o=Opt("wrong-model");File.WriteAllBytes(Path.Combine(o.SourceDirectory,a.name),data);var m=Manifest(a);m.models.Add("PhotoRestoreStudio.exe",new string('0',64));try{new InstallerEngine(m).Run(o,s=>{},CancellationToken.None).GetAwaiter().GetResult();throw new Exception("Wrong model accepted");}catch(IOException ex){Check(ex.Message=="HASH_MISMATCH","Wrong model error");}Check(!Directory.Exists(o.Destination),"Unverified model installed");});
            Test("unmanaged cache contents are never removed",()=>{var o=Opt("foreign-cache");Directory.CreateDirectory(o.CacheDirectory);File.WriteAllText(Path.Combine(o.CacheDirectory,"other.txt"),"keep");try{new InstallerEngine(Manifest(a)).Run(o,s=>{},CancellationToken.None).GetAwaiter().GetResult();throw new Exception("Unmanaged cache accepted");}catch(IOException ex){Check(ex.Message=="INVALID_CACHE","Wrong cache error");}Check(File.Exists(Path.Combine(o.CacheDirectory,"other.txt")),"Foreign cache data lost");});
            Test("GUI renders RUS and EN",()=>{Application.EnableVisualStyles();using(var form=new SetupWindow()) {form.Controls.OfType<TextBox>().Single().Text=@"D:\Apps\PhotoRestoreStudio";form.Show();Application.DoEvents();var combo=form.Controls.OfType<ComboBox>().Single();foreach(var language in new[]{0,1}) {combo.SelectedIndex=language;Application.DoEvents();using(var bitmap=new Bitmap(form.Width,form.Height)) {form.DrawToBitmap(bitmap,new Rectangle(Point.Empty,form.Size));bitmap.Save(Path.Combine(root,language==0?"setup-ru.png":"setup-en.png"));}}form.Close();}});
            Console.WriteLine("OK "+passed+" installer checks");return 0;
        } catch(Exception ex) {Console.Error.WriteLine(ex);return 1;}
    }
}
