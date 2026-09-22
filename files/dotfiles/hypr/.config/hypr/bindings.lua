-- Keep only your personal keybinding overrides here. Add new bindings or
-- unbind defaults before replacing them.

-- See current bindings and descriptions:
--   omarchy menu keybindings --print

-- Personal bindings ported from the pre-quattro Hyprland .conf config.
hl.unbind("SUPER + SHIFT + F")
hl.unbind("SUPER + SHIFT + E")
o.bind("SUPER + SHIFT + E", "File manager", { launch = "nautilus --new-window" })

hl.unbind("SUPER + SHIFT + W")
o.bind("SUPER + SHIFT + W", "Typora", { launch = "typora --enable-wayland-ime" })

-- omacalc has a reproducible bug where the numpad stops sending digits after
-- it opens (floating or tiled, focus forced or not) -- switched to
-- gnome-calculator instead. Omarchy's defaults bind omacalc on three keys:
-- SUPER + SHIFT + C, SUPER + CTRL + Q, and the physical XF86Calculator key.
hl.unbind("SUPER + SHIFT + C")
o.bind("SUPER + SHIFT + C", "Calculator", { launch = "gnome-calculator" })

hl.unbind("SUPER + CTRL + Q")
o.bind("SUPER + CTRL + Q", "Calculator", { launch = "gnome-calculator" })

hl.unbind("XF86Calculator")
o.bind("XF86Calculator", "Calculator", { launch = "gnome-calculator" })

o.window("org.gnome.Calculator", { float = true })
o.window("org.gnome.Calculator", { center = true })

o.bind("SUPER + SHIFT + H", "Email", { launch = "thunderbird" })

hl.unbind("SUPER + SHIFT + S")
o.bind("SUPER + SHIFT + S", "Hyprmon", { tui = "hyprmon" })
o.bind("SUPER + SHIFT + CTRL + S", "External only", [[sh -c '[ "$(hyprctl monitors | grep -c Monitor)" -gt 1 ] && hyprctl keyword monitor "eDP-1, disable"']])
o.bind("SUPER + SHIFT + ALT + S", "Laptop screen on", [[hyprctl keyword monitor "eDP-1, preferred, auto, 1.25"]])

o.bind("SUPER + SHIFT + ESCAPE", "Suspend", "systemctl suspend")
o.bind("SUPER + SHIFT + code:49", "Restart Espanso", "espanso restart")

o.bind("mouse:8", nil, hl.dsp.focus({ workspace = "e-1" }))
o.bind("mouse:9", nil, hl.dsp.focus({ workspace = "e+1" }))

local numpad_workspaces = {
  KP_End = 1,
  KP_Down = 2,
  KP_Next = 3,
  KP_Left = 4,
  KP_Begin = 5,
  KP_Right = 6,
  KP_Home = 7,
  KP_Up = 8,
  KP_Prior = 9,
  KP_Insert = 10,
}

for key, workspace in pairs(numpad_workspaces) do
  o.bind("SUPER + " .. key, "Switch to workspace " .. workspace, hl.dsp.focus({ workspace = tostring(workspace) }))
  o.bind("SUPER + SHIFT + " .. key, "Move window to workspace " .. workspace, hl.dsp.window.move({ workspace = tostring(workspace) }))
end
