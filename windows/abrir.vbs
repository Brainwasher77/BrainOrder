' Abre BrainOrder sin mostrar la ventana negra de la consola.
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
appdata = sh.ExpandEnvironmentStrings("%APPDATA%")
sup = appdata & "\BrainOrder"
sh.Run "cmd /c """ & sup & "\abrir.cmd""", 0, False
