import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/AppShell';
import { RequireAuth } from '@/components/RequireAuth';
import { BenchmarkPage } from '@/pages/BenchmarkPage';
import { HomePage } from '@/pages/HomePage';
import { JobDetailPage } from '@/pages/JobDetailPage';
import { JobsPage } from '@/pages/JobsPage';
import { LoginPage } from '@/pages/LoginPage';
import { ProfilePage } from '@/pages/ProfilePage';
import { RecommendationsPage } from '@/pages/RecommendationsPage';
import { RegisterPage } from '@/pages/RegisterPage';

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/profile"
          element={
            <RequireAuth>
              <ProfilePage />
            </RequireAuth>
          }
        />
        <Route
          path="/recommendations"
          element={
            <RequireAuth>
              <RecommendationsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/benchmark"
          element={
            <RequireAuth>
              <BenchmarkPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
