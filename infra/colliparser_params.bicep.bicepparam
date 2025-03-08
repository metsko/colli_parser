using 'azure.bicep'

param location = 'westeurope'

param prefix = 'colli-parser'

param storageAccountName = 'colliparsersa123'  // Ensure this is globally unique

param functionAppName = 'colli-parser-func'

param planName = 'colli-parser-plan'

param appInsightsName = 'colli-parser-ai'

param keyVaultName = 'colli-parser-kv123'  // Ensure this is globally unique

// param acrUserManagedIdentityID = '/subscriptions/3822efed-10fe-4b45-9ab1-6865bc39f41f/resourcegroups/colli_parser/providers/Microsoft.ManagedIdentity/userAssignedIdentities/func_acr_pull'
