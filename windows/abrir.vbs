' Abre SpotiSync sin mostrar la ventana negra de la consola.
Set sh = CreateObject("WScript.Shell")
sup = sh.ExpandEnvironmentStrings("%APPDATA%") & "\SpotiSync"
sh.Run "cmd /c """ & sup & "\abrir.cmd""", 0, False
