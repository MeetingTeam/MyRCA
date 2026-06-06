import { useState, useEffect } from 'react'
import { Key, Plus, Trash2, Check, X, Eye, EyeOff } from 'lucide-react'

const PROVIDERS = [
  { id: 'anthropic', name: 'Anthropic', models: ['claude-sonnet-4-6', 'claude-opus-4-5', 'claude-3-5-sonnet'] },
  { id: 'openai', name: 'OpenAI', models: ['gpt-4o', 'gpt-4-turbo', 'o1-preview'] },
  { id: 'google', name: 'Google AI', models: ['gemini-2.0-flash', 'gemini-pro'] },
]

const DEFAULT_ACTIVE_MODEL = 'anthropic:claude-sonnet-4-6'

export default function ApiKeysPage() {
  const [keys, setKeys] = useState({})
  const [activeModel, setActiveModel] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [formData, setFormData] = useState({ provider: '', apiKey: '', model: '' })
  const [showKey, setShowKey] = useState({})

  useEffect(() => {
    try {
      const saved = localStorage.getItem('rca-api-keys')
      const savedModel = localStorage.getItem('rca-active-model')
      if (saved) setKeys(JSON.parse(saved))
      setActiveModel(savedModel || DEFAULT_ACTIVE_MODEL)
    } catch (e) {
      console.error('Invalid API keys data, resetting')
      localStorage.removeItem('rca-api-keys')
    }
  }, [])

  const saveKey = () => {
    if (!formData.provider || !formData.apiKey || !formData.model) return
    const newKeys = { ...keys, [formData.provider]: { apiKey: formData.apiKey, model: formData.model } }
    setKeys(newKeys)
    localStorage.setItem('rca-api-keys', JSON.stringify(newKeys))
    setShowForm(false)
    setFormData({ provider: '', apiKey: '', model: '' })
  }

  const deleteKey = (provider) => {
    const newKeys = { ...keys }
    delete newKeys[provider]
    setKeys(newKeys)
    localStorage.setItem('rca-api-keys', JSON.stringify(newKeys))
    if (activeModel.startsWith(provider + ':')) {
      setActiveModel(DEFAULT_ACTIVE_MODEL)
      localStorage.setItem('rca-active-model', DEFAULT_ACTIVE_MODEL)
    }
  }

  const setActive = (provider, model) => {
    const modelKey = `${provider}:${model}`
    setActiveModel(modelKey)
    localStorage.setItem('rca-active-model', modelKey)
  }

  const maskKey = (key) => key ? `${key.slice(0, 8)}${'•'.repeat(12)}${key.slice(-4)}` : ''

  const getProviderName = (id) => PROVIDERS.find(p => p.id === id)?.name || id

  const selectedProvider = PROVIDERS.find(p => p.id === formData.provider)

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">API Keys</h1>
          <p className="text-gray-400 mt-1">Configure LLM API keys for RCA reasoning</p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition"
        >
          <Plus size={16} /> Add Key
        </button>
      </div>

      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-dark-800 border border-gray-700 rounded-lg p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Add API Key</h2>
              <button onClick={() => setShowForm(false)} className="text-gray-400 hover:text-white">
                <X size={20} />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Provider</label>
                <select
                  value={formData.provider}
                  onChange={(e) => setFormData({ ...formData, provider: e.target.value, model: '' })}
                  className="w-full bg-dark-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="">Select provider...</option>
                  {PROVIDERS.map(p => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">API Key</label>
                <input
                  type="password"
                  value={formData.apiKey}
                  onChange={(e) => setFormData({ ...formData, apiKey: e.target.value })}
                  placeholder="sk-..."
                  className="w-full bg-dark-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">Default Model</label>
                <select
                  value={formData.model}
                  onChange={(e) => setFormData({ ...formData, model: e.target.value })}
                  disabled={!formData.provider}
                  className="w-full bg-dark-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
                >
                  <option value="">Select model...</option>
                  {selectedProvider?.models.map(m => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => setShowForm(false)}
                  className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition"
                >
                  Cancel
                </button>
                <button
                  onClick={saveKey}
                  disabled={!formData.provider || !formData.apiKey || !formData.model}
                  className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Save Key
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="mb-6 p-4 bg-dark-800 border border-gray-700 rounded-lg">
        <div className="flex items-center gap-2 text-sm text-gray-400 mb-2">
          <Key size={16} className="text-blue-400" />
          <span>Active Model</span>
        </div>
        <div className="text-lg font-medium text-white">
          {activeModel || 'No model selected'}
        </div>
      </div>

      {Object.keys(keys).length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <Key size={48} className="mx-auto mb-4 opacity-50" />
          <p>No API keys configured</p>
          <p className="text-sm mt-1">Add your first API key to enable LLM reasoning</p>
        </div>
      ) : (
        <div className="space-y-3">
          {Object.entries(keys).map(([provider, config]) => {
            const isActive = activeModel === `${provider}:${config.model}`
            return (
              <div
                key={provider}
                className={`p-4 bg-dark-800 border rounded-lg flex items-center justify-between ${
                  isActive ? 'border-blue-500' : 'border-gray-700'
                }`}
              >
                <div className="flex items-center gap-4">
                  <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                    isActive ? 'bg-blue-600' : 'bg-gray-700'
                  }`}>
                    <Key size={20} />
                  </div>
                  <div>
                    <div className="font-medium flex items-center gap-2">
                      {getProviderName(provider)}
                      {isActive && (
                        <span className="text-xs bg-blue-600 px-2 py-0.5 rounded">Active</span>
                      )}
                    </div>
                    <div className="text-sm text-gray-400 flex items-center gap-2">
                      <span className="font-mono">
                        {showKey[provider] ? config.apiKey : maskKey(config.apiKey)}
                      </span>
                      <button
                        onClick={() => setShowKey({ ...showKey, [provider]: !showKey[provider] })}
                        className="text-gray-500 hover:text-gray-300"
                      >
                        {showKey[provider] ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                    <div className="text-xs text-gray-500 mt-1">Model: {config.model}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {!isActive && (
                    <button
                      onClick={() => setActive(provider, config.model)}
                      className="p-2 text-gray-400 hover:text-green-400 hover:bg-gray-700 rounded transition"
                      title="Set as active"
                    >
                      <Check size={18} />
                    </button>
                  )}
                  <button
                    onClick={() => deleteKey(provider)}
                    className="p-2 text-gray-400 hover:text-red-400 hover:bg-gray-700 rounded transition"
                    title="Delete key"
                  >
                    <Trash2 size={18} />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
