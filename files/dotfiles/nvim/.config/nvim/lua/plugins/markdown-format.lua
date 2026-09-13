return {
  {
    "mason-org/mason.nvim",
    opts = function(_, opts)
      opts.ensure_installed = opts.ensure_installed or {}
      vim.list_extend(opts.ensure_installed, { "prettier" })
    end,
  },
  {
    "stevearc/conform.nvim",
    optional = true,
    opts = function(_, opts)
      opts.formatters = opts.formatters or {}
      opts.formatters.prettier = vim.tbl_deep_extend("force", opts.formatters.prettier or {}, {
        prepend_args = function(_, ctx)
          local ft = vim.bo[ctx.buf].filetype
          if ft == "markdown" or ft == "markdown.mdx" then
            return { "--prose-wrap", "always" }
          end
          return {}
        end,
      })
      -- LazyVim's markdown extra chains prettier + markdownlint-cli2 +
      -- markdown-toc on every :w. markdownlint-cli2 alone measured ~0.9s on a
      -- 450KB prose file (Node CLI startup + full-document lint), which is
      -- where "saving takes several seconds" on a large document comes from.
      -- Its default rules (line length, one H1 per doc) are code-style
      -- conventions anyway, not meaningful for prose. Keep just prettier.
      opts.formatters_by_ft = opts.formatters_by_ft or {}
      opts.formatters_by_ft["markdown"] = { "prettier" }
      opts.formatters_by_ft["markdown.mdx"] = { "prettier" }
    end,
  },
  {
    -- Same markdownlint-cli2 cost as above, but on nvim-lint's side: LazyVim
    -- wires it to InsertLeave (as well as BufWritePost/BufReadPost), so every
    -- pause while drafting prose — not just saving — re-spawns a ~1s lint of
    -- the whole document. Disable it for markdown; conform above already
    -- dropped it from the save path, so nothing else depends on it running.
    "mfussenegger/nvim-lint",
    optional = true,
    opts = function(_, opts)
      opts.linters_by_ft = opts.linters_by_ft or {}
      opts.linters_by_ft["markdown"] = {}
    end,
  },
}
