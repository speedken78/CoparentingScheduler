import { useEffect } from 'react';
import { useCaseStore } from '../store/case';
import { casesApi } from '../api/cases';
import { useAuthStore } from '../store/auth';

export const useCurrentCase = () => {
  const { currentCase, cases, setCurrentCase, setCases } = useCaseStore();
  const { isAuthenticated } = useAuthStore();

  useEffect(() => {
    if (!isAuthenticated || cases.length > 0) return;
    casesApi.list().then(list => {
      setCases(list);
      if (list.length > 0 && !currentCase) setCurrentCase(list[0]);
    }).catch(() => {});
  }, [isAuthenticated]);

  return { currentCase, cases, setCurrentCase };
};
