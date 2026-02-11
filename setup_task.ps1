Unregister-ScheduledTask -TaskName 'InternshipScanner' -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute 'C:\Users\jayesh.sahasi\internship-finder\run_scanner.bat' -WorkingDirectory 'C:\Users\jayesh.sahasi\internship-finder'
$trigger = New-ScheduledTaskTrigger -Daily -At '8:00AM'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'InternshipScanner' -Action $action -Trigger $trigger -Settings $settings -Description 'Daily internship scanner - sends email digest of new postings'
