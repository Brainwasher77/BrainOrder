' Abre BrainOrder sin mostrar la ventana negra de la consola.
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
appdata = sh.ExpandEnvironmentStrings("%APPDATA%")
sup = appdata & "\BrainOrder"
If Not fs.FileExists(sup & "\abrir.cmd") And fs.FileExists(appdata & "\SpotiSync\abrir.cmd") Then sup = appdata & "\SpotiSync"
sh.Run "cmd /c """ & sup & "\abrir.cmd""", 0, False
