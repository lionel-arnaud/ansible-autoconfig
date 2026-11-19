require 'json'

account = Account.find_by(name: ENV.fetch('DOCUSEAL_ACCOUNT_NAME'))

if account.nil?
  puts 'SKIPPED: DocuSeal account does not exist yet'
  exit 0
end

templates = JSON.parse(ENV.fetch('DOCUSEAL_EMAIL_TEMPLATES'))
changed = false

templates.each do |key, values|
  config = AccountConfig.find_or_initialize_by(account:, key:)
  current = config.value.is_a?(Hash) ? config.value : {}
  desired = current.merge(values)

  next if config.persisted? && current == desired

  config.value = desired
  config.save!
  changed = true
end

puts(changed ? 'CHANGED: DocuSeal email templates updated' : 'OK: DocuSeal email templates already current')
