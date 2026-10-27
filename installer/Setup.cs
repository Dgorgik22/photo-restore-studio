using System;
using System.Drawing;
using System.IO;
using System.Net;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

[assembly: AssemblyTitle("Photo Restore Studio Setup")]
[assembly: AssemblyProduct("Photo Restore Studio — Alpha Lite")]
[assembly: AssemblyCompany("Photo Restore Studio")]
[assembly: AssemblyVersion("0.25.1.0")]
[assembly: AssemblyFileVersion("0.25.1.0")]
[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8",FrameworkDisplayName=".NET Framework 4.8")]

namespace PhotoRestoreSetup {
    public sealed class SetupWindow:Form {
        readonly Label intro=new Label(),location=new Label(),hint=new Label(),state=new Label(),license=new Label();
        readonly TextBox destination=new TextBox(); readonly Button browse=new Button(),install=new Button(),cancel=new Button(),launch=new Button();
        readonly CheckBox shortcut=new CheckBox(),cleanup=new CheckBox();readonly ComboBox language=new ComboBox();readonly ProgressBar progress=new ProgressBar();
        CancellationTokenSource cancellation;bool working,complete;bool english;Status lastStatus;string installed;
        string T(string ru,string en) {return english?en:ru;}
        public SetupWindow() {
            Text="Photo Restore Studio — Alpha Lite Setup";ClientSize=new Size(720,460);MinimumSize=MaximumSize=Size;
            StartPosition=FormStartPosition.CenterScreen;BackColor=Color.FromArgb(35,35,35);ForeColor=Color.Gainsboro;Font=new Font("Segoe UI",10);
            Icon=Icon.ExtractAssociatedIcon(Assembly.GetExecutingAssembly().Location);MaximizeBox=false;AutoScaleMode=AutoScaleMode.Dpi;
            var title=new Label {Text="PHOTO RESTORE STUDIO",Font=new Font("Segoe UI",17,FontStyle.Bold),AutoSize=true,Location=new Point(24,20)};Controls.Add(title);
            var badge=new Label {Text="ALPHA LITE  /  0.25",AutoSize=true,ForeColor=Color.Silver,Location=new Point(26,58)};Controls.Add(badge);
            language.SetBounds(608,24,86,28);language.DropDownStyle=ComboBoxStyle.DropDownList;language.Items.AddRange(new object[]{"RUS","EN"});
            english=System.Globalization.CultureInfo.CurrentUICulture.TwoLetterISOLanguageName!="ru";language.SelectedIndex=english?1:0;
            language.SelectedIndexChanged+=(s,e)=>{english=language.SelectedIndex==1;Labels();};Controls.Add(language);
            intro.SetBounds(24,93,672,49);Controls.Add(intro);location.SetBounds(24,148,672,24);Controls.Add(location);
            destination.SetBounds(24,178,566,28);destination.BackColor=Color.FromArgb(24,24,24);destination.ForeColor=ForeColor;destination.BorderStyle=BorderStyle.FixedSingle;
            destination.Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","PhotoRestoreStudio");Controls.Add(destination);
            browse.SetBounds(600,176,96,31);browse.Click+=(s,e)=>ChooseFolder();Controls.Add(browse);
            shortcut.SetBounds(24,220,672,25);shortcut.Checked=true;Controls.Add(shortcut);cleanup.SetBounds(24,250,672,25);cleanup.Checked=true;Controls.Add(cleanup);
            hint.SetBounds(24,287,672,28);hint.ForeColor=Color.Silver;Controls.Add(hint);
            progress.SetBounds(24,325,672,7);progress.Minimum=0;progress.Maximum=100;Controls.Add(progress);
            state.SetBounds(24,341,672,36);Controls.Add(state);
            install.SetBounds(430,398,158,36);install.BackColor=Color.FromArgb(20,115,230);install.ForeColor=Color.White;install.FlatStyle=FlatStyle.Flat;install.Click+=StartInstall;Controls.Add(install);
            cancel.SetBounds(600,398,96,36);cancel.Click+=(s,e)=>{if(working) cancellation.Cancel();else Close();};Controls.Add(cancel);
            launch.SetBounds(244,398,174,36);launch.Visible=false;launch.Click+=(s,e)=>{try{System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(Path.Combine(installed,"PhotoRestoreStudio.exe")){WorkingDirectory=installed,UseShellExecute=true});Close();}catch(Exception ex){MessageBox.Show(this,ex.Message,Text);}};Controls.Add(launch);
            license.SetBounds(24,393,204,48);license.Font=new Font("Segoe UI",8);license.ForeColor=Color.Silver;Controls.Add(license);
            FormClosing+=(s,e)=>{if(working){e.Cancel=true;cancellation.Cancel();}};
            Labels();
        }
        void ChooseFolder() {
            var parent=Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            try {var entered=Path.GetDirectoryName(destination.Text);if(Directory.Exists(entered))parent=entered;}catch(ArgumentException){}
            using(var dialog=new FolderBrowserDialog {Description=T("Выберите родительскую папку установки","Choose the installation parent folder"),SelectedPath=parent})
                if(dialog.ShowDialog(this)==DialogResult.OK) destination.Text=Path.Combine(dialog.SelectedPath,"PhotoRestoreStudio");
        }
        void Labels() {
            intro.Text=T("Установщик сам скачает и проверит программу. Если ZIP-части лежат рядом с Setup.exe, повторной загрузки не будет.","Setup downloads and verifies the application. ZIP parts next to Setup.exe are reused without downloading again.");
            location.Text=T("Папка установки — выберите новую папку","Installation folder — choose a new folder");browse.Text=T("Выбрать…","Browse…");
            shortcut.Text=T("Создать ярлык на рабочем столе","Create a desktop shortcut");cleanup.Text=T("Удалить скачанные установщиком архивы после установки","Remove installer downloads after installation");
            hint.Text=T("Загрузка: около 4 ГБ. Для установки желательно 12 ГБ свободного места.","Download: about 4 GB. Allow 12 GB free space during installation.");
            install.Text=complete?T("Установлено","Installed"):T("Установить","Install");cancel.Text=working?T("Отмена","Cancel"):T("Закрыть","Close");launch.Text=T("Запустить программу","Launch application");
            license.Text=T("CodeFormer: некоммерческое использование. Лицензии включены.","CodeFormer: noncommercial use. License notices included.");
            if(lastStatus!=null) ShowStatus(lastStatus);else state.Text=T("Готово к установке","Ready to install");
        }
        void ShowStatus(Status s) {
            lastStatus=s;progress.Value=Math.Max(0,Math.Min(100,s.Percent));
            switch(s.Phase) {
                case "prepare":state.Text=T("Подготовка установки…","Preparing installation…");break;
                case "verify":state.Text=T("Проверка файлов","Verifying files")+"  "+s.Part+" / "+s.Parts;break;
                case "download":state.Text=T("Скачивание части ","Downloading part ")+s.Part+" / "+s.Parts+" · "+(s.Bytes/1048576.0).ToString("0")+" / "+(s.Total/1048576.0).ToString("0")+" MB";break;
                case "extract":state.Text=T("Установка программы…","Installing application…");break;
                case "models":state.Text=T("Проверка моделей…","Verifying models…");break;
                case "compress":state.Text=T("Сжатие библиотек без потери качества…","Compressing libraries without quality loss…");break;
                case "done":state.Text=T("Программа установлена.","Application installed.");break;
                case "shortcut":state.Text=T("Установлено. Ярлык создать не удалось — запустите программу из папки установки.","Installed. Shortcut could not be created; launch the application from its folder.");break;
                case "cleanup":state.Text=T("Установлено. Часть временных загрузок можно удалить позже.","Installed. Some temporary downloads can be removed later.");break;
            }
        }
        string ErrorText(Exception ex) {
            switch(ex.Message) {
                case "DESTINATION_EXISTS":return T("Эта папка уже существует. Выберите новую, чтобы сохранить имеющиеся файлы.","This folder already exists. Choose a new one to preserve existing files.");
                case "DISK_SPACE":return T("Недостаточно места на диске установки или временных загрузок.","Not enough space on the installation or download drive.");
                case "LINKED_PATH":return T("Выберите обычную папку без ссылок и перенаправлений.","Choose a normal folder without links or redirects.");
                case "HASH_MISMATCH":return T("Проверка файла не пройдена. Повторите установку: файл будет скачан заново.","File verification failed. Retry installation to download it again.");
                case "INVALID_ARCHIVE":return T("Архив имеет неверную структуру. Установка отменена.","Invalid archive structure. Installation was cancelled.");
                case "INVALID_CACHE":return T("Временная папка занята посторонними файлами. Установка остановлена.","The temporary folder contains unrelated files. Installation stopped.");
                case "INVALID_DESTINATION":return T("Выберите новую локальную папку установки, отдельно от временных загрузок.","Choose a new local installation folder, separate from the download cache.");
                default:return T("Не удалось завершить установку. Проверьте интернет и доступ к папке. Можно положить четыре ZIP-части рядом с Setup.exe и повторить.\n\n","Installation could not finish. Check your connection and folder access. You can place all four ZIP parts next to Setup.exe and retry.\n\n")+ex.Message;
            }
        }
        async void StartInstall(object sender,EventArgs args) {
            if(working||complete) return;
            try {InstallerEngine.ValidateDestination(destination.Text);}catch(Exception ex){MessageBox.Show(this,ErrorText(ex),Text,MessageBoxButtons.OK,MessageBoxIcon.Information);return;}
            cancellation=new CancellationTokenSource();working=true;install.Enabled=browse.Enabled=destination.Enabled=shortcut.Enabled=cleanup.Enabled=false;Labels();
            try {
                var options=new Options {Destination=destination.Text,SourceDirectory=AppDomain.CurrentDomain.BaseDirectory,
                    CacheDirectory=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"PhotoRestoreStudio","InstallerCache","0.25-alpha-lite"),
                    Shortcut=shortcut.Checked,CleanDownloads=cleanup.Checked};
                var reporter=new Progress<Status>(ShowStatus);
                installed=await Task.Run(async()=>{using(var engine=new InstallerEngine(Release.Embedded())) return await engine.Run(options,s=>((IProgress<Status>)reporter).Report(s),cancellation.Token);});
                complete=true;launch.Visible=true;
            } catch(Exception ex) {
                if(cancellation.IsCancellationRequested||ex is OperationCanceledException) state.Text=T("Установка отменена. Загрузка продолжится при следующей попытке.","Installation cancelled. Downloads can resume on the next attempt.");
                else {state.Text=T("Установка не завершена","Installation did not finish");MessageBox.Show(this,ErrorText(ex),Text,MessageBoxButtons.OK,MessageBoxIcon.Information);}
                lastStatus=null;
            } finally {
                working=false;cancellation.Dispose();install.Enabled=!complete;browse.Enabled=destination.Enabled=shortcut.Enabled=cleanup.Enabled=!complete;
                install.Text=complete?T("Установлено","Installed"):T("Повторить","Retry");cancel.Text=T("Закрыть","Close");
            }
        }
    }
    static class Program {
        [STAThread] static void Main() {
            ServicePointManager.SecurityProtocol=SecurityProtocolType.Tls12;
            Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new SetupWindow());
        }
    }
}
