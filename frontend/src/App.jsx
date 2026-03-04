import { Routes, Route } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import AuthPage from './pages/AuthPage'
import CreatePlanPage from './pages/CreatePlanPage'
import PlansPage from './pages/PlansPage'
import PlanDetailPage from './pages/PlanDetailPage'
import UnitPage from './pages/UnitPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<AuthPage />} />
      <Route path="/create-plan" element={<CreatePlanPage />} />
      <Route path="/plans" element={<PlansPage />} />
      <Route path="/plans/:id" element={<PlanDetailPage />} />
      <Route path="/units/:id" element={<UnitPage />} />
    </Routes>
  )
}

export default App
