using 'azure.bicep'

param location = 'westeurope'

param prefix = 'colli-parser'

param storageAccountName = 'colliparsersa123'  // Ensure this is globally unique

param functionAppName = 'colli-parser-func'

param planName = 'colli-parser-plan'

param appInsightsName = 'colli-parser-ai'

param keyVaultName = 'colli-parser-kv123'  // Ensure this is globally unique
