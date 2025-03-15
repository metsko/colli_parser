@description('Location for all resources')
param location string = resourceGroup().location

@description('Prefix for resource names')
param prefix string = 'colli-parser'

@description('Unique storage account name (must be globally unique, 3-24 lowercase letters and numbers)')
param storageAccountName string = 'colliparsersa123'

@description('Function App name')
param functionAppName string = '${prefix}-func'

@description('App Service Plan name')
param planName string = '${prefix}-plan'

@description('Application Insights name')
param appInsightsName string = '${prefix}-ai'

@description('Key Vault name (must be globally unique and 3-24 lowercase letters)')
param keyVaultName string = '${prefix}-kv123'

// Storage Account
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
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

// App Service Plan (Elastic Premium)
resource appServicePlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: planName
  location: location
  kind: 'functionapp,linux'
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    maximumElasticWorkerCount: 1
    reserved: true
  }
}

// Function App
resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    dailyMemoryTimeQuota: 33
    siteConfig: {
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net'
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
        {
          name: 'CHATGPT_API_TOKEN'
          value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=mistral-api-token)'
        }
        {
          name: 'TELEGRAM_TOKEN'
          value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=telegram-token)'
        }
        {
          name: 'API_TOKEN'
          value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=api-token)'
        }
        {
          name: 'SPLITWISE_API_KEY'
          value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=splitwise-api-key)'
        }
        {
          name: 'SPLITWISE_CONSUMER_KEY'
          value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=splitwise-consumer-key)'
        }
        {
          name: 'SPLITWISE_CONSUMER_SECRET'
          value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=splitwise-consumer-secret)'
        }
      ]
      linuxFxVersion: 'PYTHON|3.12'
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

resource keyVaultAccessPolicy 'Microsoft.KeyVault/vaults/accessPolicies@2023-07-01' = {
  parent: keyVault
  name: 'add'
  properties: {
    accessPolicies: [
      {
        tenantId: subscription().tenantId
        objectId: functionApp.identity.principalId
        permissions: {
          secrets: [
            'get'
            'list'
          ]
        }
      }
      {
        tenantId: subscription().tenantId
        // me
        objectId: 'a62b6f54-6000-4e17-89e5-41b19880c79a'
        permissions: {
          secrets: ['get', 'list']
        }
      }
    ]
  }
}

// Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    createMode: 'recover'
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enabledForDeployment: true
    enabledForDiskEncryption: true
    enabledForTemplateDeployment: true
  }
}
