-- Extra autostart processes.
-- o.launch_on_start("my-service")

hl.on("hyprland.start", function()
  hl.exec_cmd("[workspace 1 silent] " .. o.launch("thunderbird"))
  hl.exec_cmd("[workspace 2 silent] " .. o.launch("chromium"))
  hl.exec_cmd("[workspace 3 silent] " .. o.launch("beeper"))
  hl.exec_cmd("[workspace 4 silent] " .. o.launch("alacritty"))
  hl.exec_cmd("[workspace 6 silent] " .. o.launch("nautilus"))
  -- Google Drive is mounted by the rclone-gdrive-mount systemd user service
  -- (roles/workstation/tasks/rclone_gdrive.yml), not launched here. Running
  -- both raced for the same mountpoint and crash-looped the systemd unit.
  hl.exec_cmd(o.launch('bash "$HOME/serverannah_mount.sh"'))
  -- Only the tray indicator is launched here. kdeconnectd is already started by
  -- /etc/xdg/autostart/org.kde.kdeconnect.daemon.desktop (uwsm turns XDG
  -- autostart entries into app-org.kde.kdeconnect.daemon@autostart.service).
  -- Launching it a second time raced the first instance for UDP/TCP 1716 and
  -- left a half-initialised daemon that could not discover devices.
  hl.exec_cmd(o.launch("kdeconnect-indicator"))
end)
