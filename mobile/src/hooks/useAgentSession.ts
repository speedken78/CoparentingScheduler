import { useAgentStore } from '../store/agent';

export const useAgentSession = () => {
  const { sessionId, setSessionId, clearSession } = useAgentStore();
  return { sessionId, setSessionId, clearSession };
};
