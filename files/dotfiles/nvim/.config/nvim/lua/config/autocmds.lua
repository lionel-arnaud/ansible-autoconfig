-- Autocmds are automatically loaded on the VeryLazy event
-- Default autocmds that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/autocmds.lua
--
-- Add any additional autocmds here
-- with `vim.api.nvim_create_autocmd`
--
-- Or remove existing autocmds by their group name (which is prefixed with `lazyvim_` for the defaults)
-- e.g. vim.api.nvim_del_augroup_by_name("lazyvim_wrap_spell")

-- Spellcheck is off for markdown/text by default (see below), except inside
-- the HK book project, where it's on with French dictionary for proofreading
-- OCR'd typewritten pages.
local hk_project_dir = vim.fn.expand("~/Google Drive Perso/Rédaction/HK by Michèle Babou Kapferer")

vim.api.nvim_create_autocmd("FileType", {
  pattern = { "markdown", "markdown.mdx", "text" },
  callback = function()
    local filepath = vim.fn.expand("%:p")
    if filepath:sub(1, #hk_project_dir) == hk_project_dir then
      vim.opt_local.spell = true
      vim.opt_local.spelllang = "fr"
    else
      vim.opt_local.spell = false
    end
  end,
})
