terraform {
  required_version = ">= 1.12.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}
}

resource "random_pet" "suffix" {
  length = 1
}

resource "azurerm_resource_group" "site" {
  name     = "rg-writing-contests-finder-live"
  location = var.location

  tags = var.tags
}

resource "azurerm_static_web_app" "site" {
  name                = "writing-contests-${random_pet.suffix.id}"
  resource_group_name = azurerm_resource_group.site.name
  location            = var.location

  sku_tier = "Free"
  sku_size = "Free"

  tags = var.tags
}
