-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here

-- Spelling: LazyVim only ships <leader>us (toggle spell on/off). These fill
-- in the missing "act on the word under cursor" actions under <leader>z, in
-- the space-menu discoverable style.
local map = vim.keymap.set
map("n", "<leader>zg", "zg", { desc = "Add word to dictionary" })
map("n", "<leader>zw", "zw", { desc = "Mark word as wrong (undo add)" })
map("n", "<leader>z=", "z=", { desc = "Spelling suggestions" })
map("n", "<leader>zn", "]s", { desc = "Next misspelled word" })
map("n", "<leader>zp", "[s", { desc = "Previous misspelled word" })
