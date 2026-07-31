output "site_url" {
  value = "https://${azurerm_static_web_app.site.default_host_name}"
}

output "deployment_token" {
  value     = azurerm_static_web_app.site.api_key
  sensitive = true
}
