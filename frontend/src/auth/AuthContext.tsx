import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { api, getStoredToken, setStoredToken } from '@/api/client';

type Me = { user_id: string; name: string; email?: string } | null;

type AuthContextValue = {
  token: string | null;
  me: Me;
  loading: boolean;
  login: (user_id: string, password: string) => Promise<void>;
  register: (p: {
    user_id: string;
    name: string;
    email?: string;
    phone?: string;
    password: string;
  }) => Promise<void>;
  logout: () => void;
  refreshMe: () => Promise<void>;
};

const Ctx = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getStoredToken());
  const [me, setMe] = useState<Me>(null);
  const [loading, setLoading] = useState(true);

  const refreshMe = useCallback(async () => {
    const t = getStoredToken();
    if (!t) {
      setMe(null);
      setLoading(false);
      return;
    }
    try {
      const m = await api.me();
      setMe(m);
    } catch {
      setMe(null);
      setStoredToken(null);
      setToken(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshMe();
  }, [refreshMe]);

  useEffect(() => {
    const h = () => {
      setToken(getStoredToken());
      void refreshMe();
    };
    window.addEventListener('careergo-auth', h);
    return () => window.removeEventListener('careergo-auth', h);
  }, [refreshMe]);

  const login = useCallback(async (user_id: string, password: string) => {
    const r = await api.login({ user_id, password });
    setStoredToken(r.access_token);
    setToken(r.access_token);
    setMe({ user_id: r.user_id, name: r.name });
  }, []);

  const register = useCallback(
    async (p: { user_id: string; name: string; email?: string; phone?: string; password: string }) => {
      const r = await api.register(p);
      setStoredToken(r.access_token);
      setToken(r.access_token);
      setMe({ user_id: r.user_id, name: r.name });
    },
    [],
  );

  const logout = useCallback(() => {
    setStoredToken(null);
    setToken(null);
    setMe(null);
  }, []);

  const value = useMemo(
    () => ({
      token,
      me,
      loading,
      login,
      register,
      logout,
      refreshMe,
    }),
    [token, me, loading, login, register, logout, refreshMe],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth outside AuthProvider');
  return v;
}
