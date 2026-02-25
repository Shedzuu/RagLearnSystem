import { Routes, Route } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import AuthPage from './pages/AuthPage'
import CreatePlanPage from './pages/CreatePlanPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<AuthPage />} />
      <Route path="/create-plan" element={<CreatePlanPage />} />
    </Routes>
  )
}

export default App
