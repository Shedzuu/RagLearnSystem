import { Routes, Route } from 'react-router-dom'
import LandingPage from './pages/LandingPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      {/* Новые страницы добавлять сюда, например:
      <Route path="/auth" element={<AuthPage />} />
      <Route path="/dashboard" element={<DashboardPage />} />
      */}
    </Routes>
  )
}

export default App
