import { useAuthStore } from '../store/auth';

export const useAuth = () => {
  const { user, isAuthenticated, isLoading, login, logout, loadFromStorage } = useAuthStore();
  return { user, isAuthenticated, isLoading, login, logout, loadFromStorage };
};
