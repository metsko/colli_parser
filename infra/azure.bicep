@description('Location for all resources')
param location string = resourceGroup().location

@description('Prefix for resource names')
param prefix string = 'colli-parser'

@description('Unique storage account name (must be globally unique, 3-24 lowercase letters and numbers)')
param storageAccountName string = toLower('${prefix}sa${uniqueString(resourceGroup().id)}')

@description('Function App name')
param functionAppName string = '${prefix}-func'

@description('App Service Plan name')
param planName string = '${prefix}-plan'

@description('Application Insights name')
param appInsightsName string = '${prefix}-ai'

@description('Key Vault name (must be globally unique and 3-24 lowercase letters)')
param keyVaultName string = toLower('${prefix}-kv${uniqueString(resourceGroup().id)}')

// Storage Account
resource storageAccount 'Microsoft.Storage/storageAccounts@2021-09-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    supportsHttpsTrafficOnly: true
  }
}

// App Service Plan (Consumption)
resource appServicePlan 'Microsoft.Web/serverfarms@2021-03-01' = {
  name: planName
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    maximumElasticWorkerCount: 1
  }
}

// Function App
resource functionApp 'Microsoft.Web/sites@2021-03-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp'
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: storageAccount.properties.primaryEndpoints.blob
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'APPINSIGHTS_INSTRUMENTATIONKEY'
          value: appInsights.properties.InstrumentationKey
        }
      ]
    }
  }
}

// Application Insights
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
  }
}

// Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2021-06-01-preview' = {
  name: keyVaultName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    accessPolicies: [] // Add access policies as needed
    enabledForDeployment: true
    enabledForDiskEncryption: true
    enabledForTemplateDeployment: true
  }
}
