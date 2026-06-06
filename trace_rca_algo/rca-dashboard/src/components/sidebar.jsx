import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Users,
  FolderKanban,
  BarChart3,
  Key,
  ChevronLeft,
  ChevronRight
} from 'lucide-react'

const menuItems = [
  { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/users', icon: Users, label: 'Roles & Users' },
  { path: '/projects', icon: FolderKanban, label: 'Projects' },
  { path: '/grafana', icon: BarChart3, label: 'Grafana' },
  { path: '/api-keys', icon: Key, label: 'API Keys' },
]

export default function Sidebar({ collapsed, onToggle }) {
  return (
    <aside className={`bg-dark-800 border-r border-gray-700 flex flex-col transition-all duration-300 ${
      collapsed ? 'w-16' : 'w-60'
    }`}>
      <button
        onClick={onToggle}
        className="p-4 hover:bg-dark-700 flex items-center justify-center border-b border-gray-700"
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed ? <ChevronRight size={20} className="text-gray-400" /> : <ChevronLeft size={20} className="text-gray-400" />}
      </button>

      <nav className="flex-1 py-4">
        {menuItems.map(item => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            title={collapsed ? item.label : undefined}
            className={({ isActive }) => `
              flex items-center gap-3 px-4 py-3 mx-2 rounded-lg transition-colors
              ${isActive
                ? 'bg-blue-600/20 text-blue-400 border-l-2 border-blue-400'
                : 'text-gray-400 hover:bg-dark-700 hover:text-white'
              }
            `}
          >
            <item.icon size={20} className="flex-shrink-0" />
            <span className={`whitespace-nowrap overflow-hidden transition-all duration-300 ${
              collapsed ? 'w-0 opacity-0' : 'w-auto opacity-100'
            }`}>
              {item.label}
            </span>
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
