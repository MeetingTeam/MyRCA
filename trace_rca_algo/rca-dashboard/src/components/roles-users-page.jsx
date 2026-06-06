import { useState, useEffect } from 'react'
import { Users, Plus, Trash2, Shield, Edit2, X, Check } from 'lucide-react'
import { useAuth } from '../auth-context'

const ROLES = [
  { id: 'admin', name: 'Admin', description: 'Full access to all features', color: 'red' },
  { id: 'editor', name: 'Editor', description: 'Can view and modify incidents', color: 'yellow' },
  { id: 'viewer', name: 'Viewer', description: 'Read-only access', color: 'blue' },
]

const DEFAULT_ADMIN = { email: 'phunghung146@gmail.com', role: 'admin', name: 'Phung Hung' }

export default function RolesUsersPage() {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [formData, setFormData] = useState({ email: '', role: 'viewer' })
  const [editingUser, setEditingUser] = useState(null)

  useEffect(() => {
    const saved = localStorage.getItem('rca-users')
    if (saved) {
      try {
        setUsers(JSON.parse(saved))
      } catch {
        localStorage.removeItem('rca-users')
        setUsers([DEFAULT_ADMIN])
        localStorage.setItem('rca-users', JSON.stringify([DEFAULT_ADMIN]))
      }
    } else {
      setUsers([DEFAULT_ADMIN])
      localStorage.setItem('rca-users', JSON.stringify([DEFAULT_ADMIN]))
    }
  }, [])

  const saveUser = () => {
    if (!formData.email || !formData.role) return
    if (users.some(u => u.email === formData.email)) {
      alert('User already exists')
      return
    }
    const newUsers = [...users, { email: formData.email, role: formData.role, name: '' }]
    setUsers(newUsers)
    localStorage.setItem('rca-users', JSON.stringify(newUsers))
    setShowForm(false)
    setFormData({ email: '', role: 'viewer' })
  }

  const updateRole = (email, newRole) => {
    const newUsers = users.map(u => u.email === email ? { ...u, role: newRole } : u)
    setUsers(newUsers)
    localStorage.setItem('rca-users', JSON.stringify(newUsers))
    setEditingUser(null)
  }

  const deleteUser = (email) => {
    if (email === currentUser?.email) {
      alert('Cannot delete yourself')
      return
    }
    const newUsers = users.filter(u => u.email !== email)
    setUsers(newUsers)
    localStorage.setItem('rca-users', JSON.stringify(newUsers))
  }

  const getRoleBadgeClass = (roleId) => {
    const role = ROLES.find(r => r.id === roleId)
    if (role?.color === 'red') return 'bg-red-600'
    if (role?.color === 'yellow') return 'bg-yellow-600'
    return 'bg-blue-600'
  }

  const getRoleName = (roleId) => ROLES.find(r => r.id === roleId)?.name || roleId

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Roles & Users</h1>
          <p className="text-gray-400 mt-1">Manage user roles and permissions</p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition"
        >
          <Plus size={16} /> Add User
        </button>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-6">
        {ROLES.map(role => (
          <div key={role.id} className="p-4 bg-dark-800 border border-gray-700 rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <Shield size={18} className={
                role.color === 'red' ? 'text-red-400' :
                role.color === 'yellow' ? 'text-yellow-400' : 'text-blue-400'
              } />
              <span className="font-medium">{role.name}</span>
            </div>
            <p className="text-sm text-gray-400">{role.description}</p>
          </div>
        ))}
      </div>

      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-dark-800 border border-gray-700 rounded-lg p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Add User</h2>
              <button onClick={() => setShowForm(false)} className="text-gray-400 hover:text-white">
                <X size={20} />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Email</label>
                <input
                  type="email"
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  placeholder="user@example.com"
                  className="w-full bg-dark-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">Role</label>
                <select
                  value={formData.role}
                  onChange={(e) => setFormData({ ...formData, role: e.target.value })}
                  className="w-full bg-dark-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                >
                  {ROLES.map(r => (
                    <option key={r.id} value={r.id}>{r.name}</option>
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
                  onClick={saveUser}
                  disabled={!formData.email}
                  className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Add User
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="bg-dark-800 border border-gray-700 rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-dark-700">
            <tr>
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-400">User</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-400">Role</th>
              <th className="px-4 py-3 text-right text-sm font-medium text-gray-400">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700">
            {users.map(u => (
              <tr key={u.email} className="hover:bg-dark-700/50">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-gray-600 flex items-center justify-center">
                      <Users size={16} />
                    </div>
                    <div>
                      <div className="font-medium flex items-center gap-2">
                        {u.name || u.email}
                        {u.email === currentUser?.email && (
                          <span className="text-xs bg-green-600 px-2 py-0.5 rounded">You</span>
                        )}
                      </div>
                      {u.name && <div className="text-sm text-gray-400">{u.email}</div>}
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  {editingUser === u.email ? (
                    <div className="flex items-center gap-2">
                      <select
                        defaultValue={u.role}
                        onChange={(e) => updateRole(u.email, e.target.value)}
                        className="bg-dark-700 border border-gray-600 rounded px-2 py-1 text-sm"
                      >
                        {ROLES.map(r => (
                          <option key={r.id} value={r.id}>{r.name}</option>
                        ))}
                      </select>
                      <button
                        onClick={() => setEditingUser(null)}
                        className="text-gray-400 hover:text-white"
                      >
                        <X size={16} />
                      </button>
                    </div>
                  ) : (
                    <span className={`text-xs px-2 py-1 rounded ${getRoleBadgeClass(u.role)}`}>
                      {getRoleName(u.role)}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <button
                      onClick={() => setEditingUser(u.email)}
                      className="p-2 text-gray-400 hover:text-blue-400 hover:bg-gray-700 rounded transition"
                      title="Edit role"
                    >
                      <Edit2 size={16} />
                    </button>
                    <button
                      onClick={() => deleteUser(u.email)}
                      disabled={u.email === currentUser?.email}
                      className="p-2 text-gray-400 hover:text-red-400 hover:bg-gray-700 rounded transition disabled:opacity-50 disabled:cursor-not-allowed"
                      title="Delete user"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
