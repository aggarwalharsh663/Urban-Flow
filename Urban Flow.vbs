' Urban Flow - Adaptive Traffic Signal System
' Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
'
' Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
' Any additions, modifications, or contributed files to this project automatically
' and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
strCurDir = FSO.GetParentFolderName(WScript.ScriptFullName)

If FSO.FileExists(strCurDir & "\frontend\node_modules\electron\dist\electron.exe") Then
    WshShell.CurrentDirectory = strCurDir & "\frontend"
    WshShell.Run """" & strCurDir & "\frontend\node_modules\electron\dist\electron.exe"" """ & strCurDir & "\frontend""", 1, False
ElseIf FSO.FileExists(strCurDir & "\Urban Flow.bat") Then
    WshShell.Run """" & strCurDir & "\Urban Flow.bat""", 1, False
Else
    MsgBox "Urban Flow desktop runtime was not found. Please verify that frontend\node_modules\electron\dist\electron.exe exists.", 16, "Urban Flow Launch Error"
End If
