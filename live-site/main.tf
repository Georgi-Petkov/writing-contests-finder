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

  lifecycle {
    ignore_changes = [repository_branch, repository_url]

    precondition {
      condition = contains(
        ["westus2", "centralus", "eastus2", "westeurope", "eastasia"],
        lower(var.location)
      )
      error_message = "Static Web Apps Free tier isn't available in ${var.location}. Pick a region from the supported list before applying."
    }

    postcondition {
      condition     = self.sku_tier == "Free" && self.sku_size == "Free"
      error_message = "azurerm_static_web_app did not come back on the Free SKU — check for provider drift or a config mistake before this goes further."
    }
  }
}
