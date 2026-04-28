# MILESTONE_1_8.md｜React Native App 實作

> Phase 1 最後一個 Milestone：把後端 API 接上行動端介面。
> 閱讀順序：本文件 → 後端 API 文件（FastAPI 自動產生的 `/docs`）
> 完成後跑 §11 DoD，驗收 4 個核心畫面與端到端流程。

---

## 0. 本 Milestone 的交付範圍

| 交付項目 | 說明 |
|---|---|
| 專案初始化 | Expo + TypeScript + 必要套件 |
| `src/theme/` | 設計系統（顏色、間距、字型） |
| `src/api/` | 後端 API client（含 auth、agent、schedules、reports） |
| `src/store/` | Zustand global state |
| `src/screens/` | 四個主畫面 + 登入畫面 |
| `src/components/` | 共用元件 |
| `src/navigation/` | 導覽結構 |
| OAuth 整合 | Google Sign-In + GCal scope |
| Push 通知 | Expo Notifications（基礎設定，實際推送 Phase 2） |

---

## 1. 技術棧

| 類別 | 套件 | 版本 |
|---|---|---|
| Framework | Expo SDK | 52+ |
| 語言 | TypeScript | 5.x |
| Navigation | React Navigation | 6.x |
| State | Zustand | 4.x |
| API Client | Axios | 1.x |
| 表單 | React Hook Form | 7.x |
| 日期處理 | date-fns | 3.x |
| OAuth | expo-auth-session | 5.x |
| 安全儲存 | expo-secure-store | 13.x |
| 行事曆 UI | react-native-calendars | 1.x |

**為什麼選 Expo 而非 bare React Native**：你已經熟悉 poker-coach 的 Expo 棧，OTA 更新方便，原生模組需求不高（不需 Bluetooth、藍牙等），Expo 完全夠用。

**為什麼選 Zustand 而非 Redux**：State 不複雜，Zustand 的 boilerplate 少很多，TypeScript 支援好。

---

## 2. 專案目錄結構

```
mobile/
├── app.json                    # Expo 設定
├── App.tsx                     # 進入點
├── babel.config.js
├── tsconfig.json
├── package.json
├── .env                        # 環境變數（API URL 等）
├── assets/
│   ├── icon.png
│   └── splash.png
└── src/
    ├── theme/
    │   ├── colors.ts           # 設計系統的顏色
    │   ├── spacing.ts          # 間距、圓角
    │   ├── typography.ts       # 字型大小、行高
    │   └── index.ts
    │
    ├── api/
    │   ├── client.ts           # Axios instance + interceptors
    │   ├── auth.ts             # auth endpoints
    │   ├── agent.ts            # agent endpoints
    │   ├── schedules.ts        # schedules endpoints
    │   ├── reports.ts          # reports endpoints
    │   ├── cases.ts            # cases / children endpoints
    │   └── types.ts            # API response 型別
    │
    ├── store/
    │   ├── auth.ts             # 登入狀態、user 資訊
    │   ├── case.ts             # 目前選擇的案件
    │   └── agent.ts            # AI 對話 session 狀態
    │
    ├── screens/
    │   ├── LoginScreen.tsx
    │   ├── OnboardingScreen.tsx     # 首次登入後建立第一個案件
    │   ├── HomeScreen.tsx
    │   ├── ChatScreen.tsx
    │   ├── CalendarScreen.tsx
    │   ├── RecordsScreen.tsx
    │   ├── EventDetailScreen.tsx    # 點擊事件後的詳情
    │   └── ReportPreviewScreen.tsx  # PDF 預覽 / 下載
    │
    ├── components/
    │   ├── ui/
    │   │   ├── Button.tsx
    │   │   ├── Card.tsx
    │   │   ├── Pill.tsx              # 「我」「對方」標籤
    │   │   ├── StatCard.tsx
    │   │   ├── EventCard.tsx
    │   │   ├── AlertBanner.tsx
    │   │   └── EmptyState.tsx
    │   ├── chat/
    │   │   ├── MessageBubble.tsx
    │   │   ├── ClarifyOptions.tsx    # AI 澄清選項按鈕
    │   │   ├── DoneBox.tsx           # 「✓ 已建立」綠色框
    │   │   └── ChatInput.tsx
    │   └── calendar/
    │       ├── MonthGrid.tsx         # 月檢視主元件
    │       ├── DayCell.tsx
    │       └── EventList.tsx
    │
    ├── navigation/
    │   ├── RootNavigator.tsx        # Auth / Main 切換
    │   ├── MainTabNavigator.tsx     # 底部 4 tab
    │   └── types.ts                 # navigation params 型別
    │
    ├── hooks/
    │   ├── useAuth.ts
    │   ├── useCurrentCase.ts
    │   └── useAgentSession.ts
    │
    └── utils/
        ├── secureStorage.ts          # 包裝 expo-secure-store
        ├── formatDate.ts
        └── constants.ts
```

---

## 3. 設計系統（`src/theme/`）

從你看到的 UI mockup 萃取出設計 tokens。

### 3.1 `colors.ts`

```typescript
// src/theme/colors.ts

export const colors = {
  // Brand（藍：我）
  brand: {
    primary: '#4a6fa5',
    primaryDark: '#3a5a8a',
    primaryLight: '#dce8f7',
    primaryAccent: '#1e4a80',  // 文字用
  },

  // Counterparty（橘：對方）
  counterparty: {
    primary: '#c87941',
    primaryLight: '#fde8d4',
    primaryAccent: '#7a3d10',
  },

  // 衝突警示（黃）
  conflict: {
    background: '#fef9ec',
    border: '#f5d87a',
    text: '#6a4800',
    cellBackground: '#fef0cc',
    cellText: '#7a5000',
  },

  // 狀態
  status: {
    successBackground: '#e0f0e0',
    successText: '#1a5a1a',
    successBorder: '#8aba8a',
    dangerBackground: '#fde0e0',
    dangerText: '#7a1a1a',
    warningBackground: '#fef0cc',
    warningText: '#7a5000',
  },

  // 背景
  background: {
    primary: '#ffffff',
    secondary: '#f5f6f8',
    tertiary: '#fafbfc',
    card: '#ffffff',
  },

  // 文字
  text: {
    primary: '#1a1a1a',
    secondary: '#6a6a6a',
    tertiary: '#9a9a9a',
    inverse: '#ffffff',
  },

  // Border
  border: {
    light: 'rgba(0,0,0,0.08)',
    medium: 'rgba(0,0,0,0.15)',
  },
};
```

### 3.2 `spacing.ts`

```typescript
// src/theme/spacing.ts
export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
};

export const radius = {
  sm: 6,
  md: 10,
  lg: 12,
  xl: 16,
  pill: 999,
};
```

### 3.3 `typography.ts`

```typescript
// src/theme/typography.ts
export const typography = {
  // Heading
  h1: { fontSize: 22, fontWeight: '500' as const, lineHeight: 30 },
  h2: { fontSize: 17, fontWeight: '500' as const, lineHeight: 24 },
  h3: { fontSize: 15, fontWeight: '500' as const, lineHeight: 22 },

  // Body
  bodyLarge: { fontSize: 14, fontWeight: '400' as const, lineHeight: 22 },
  body: { fontSize: 13, fontWeight: '400' as const, lineHeight: 20 },
  bodyMedium: { fontSize: 13, fontWeight: '500' as const, lineHeight: 20 },

  // Caption
  caption: { fontSize: 11, fontWeight: '400' as const, lineHeight: 16 },
  captionMedium: { fontSize: 11, fontWeight: '500' as const, lineHeight: 16 },

  // Section heading（大寫小字）
  sectionLabel: {
    fontSize: 11,
    fontWeight: '500' as const,
    letterSpacing: 0.5,
    textTransform: 'uppercase' as const,
  },
};
```

---

## 4. API Client（`src/api/`）

### 4.1 `client.ts`

```typescript
// src/api/client.ts
import axios, { AxiosInstance, AxiosError } from 'axios';
import { secureStorage } from '../utils/secureStorage';

const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

// 請求攔截器：自動帶 access token
apiClient.interceptors.request.use(async (config) => {
  const token = await secureStorage.getAccessToken();
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 回應攔截器:401 時自動 refresh token
let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as any;

    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      if (isRefreshing) {
        return new Promise((resolve) => {
          refreshSubscribers.push((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            resolve(apiClient(originalRequest));
          });
        });
      }

      isRefreshing = true;
      try {
        const refreshToken = await secureStorage.getRefreshToken();
        if (!refreshToken) throw new Error('No refresh token');

        const response = await axios.post(`${API_BASE_URL}/auth/refresh`, {
          refresh_token: refreshToken,
        });
        const newToken = response.data.access_token;
        await secureStorage.setAccessToken(newToken);

        refreshSubscribers.forEach((cb) => cb(newToken));
        refreshSubscribers = [];
        isRefreshing = false;

        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return apiClient(originalRequest);
      } catch (refreshError) {
        isRefreshing = false;
        refreshSubscribers = [];
        await secureStorage.clearTokens();
        // 觸發重新登入（透過事件或全域 store）
        throw refreshError;
      }
    }

    return Promise.reject(error);
  }
);
```

### 4.2 `types.ts`（API 型別定義）

```typescript
// src/api/types.ts

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: 'parent' | 'lawyer' | 'social_worker' | 'admin';
  gcal_scope_granted: boolean;
}

export interface Case {
  id: string;
  case_name: string;
  court_case_no: string | null;
  custody_type: 'sole' | 'joint' | 'split';
  custody_ratio: Record<string, number> | null;
  timezone: string;
  my_relation: 'parent_a' | 'parent_b' | 'lawyer' | 'observer';
  created_at: string;
}

export interface Child {
  id: string;
  display_name: string;
  birth_date: string;
  age_years: number;
  notes: string | null;
}

export interface CustodyEvent {
  id: string;
  starts_at: string;        // ISO 8601
  ends_at: string;
  custodian_id: string;
  status: 'scheduled' | 'confirmed' | 'in_progress' | 'completed' | 'missed' | 'disputed' | 'cancelled';
  rule_id: string | null;
  handover_location: string | null;
  notes: string | null;
}

export interface CustodyRule {
  id: string;
  rrule: string;
  custodian_id: string;
  start_time: string;       // "07:30"
  end_time: string;         // "17:30"
  effective_from: string;
  effective_until: string | null;
  source: 'court_order' | 'mutual_agreement' | 'unilateral';
}

export interface AgentMessageResponse {
  session_id: string;
  reply: string;
  actions_taken: AgentAction[];
  requires_clarification: boolean;
  clarification_options: ClarificationOption[];
}

export interface AgentAction {
  tool: string;
  input: Record<string, any>;
  result: Record<string, any>;
}

export interface ClarificationOption {
  label: string;
  interpretation_note: string;
}

export interface Report {
  id: string;
  pdf_path: string;
  pdf_sha256: string;
  last_audit_id: number;
  last_audit_hash: string;
  generated_at: string;
}
```

### 4.3 `agent.ts`

```typescript
// src/api/agent.ts
import { apiClient } from './client';
import { AgentMessageResponse } from './types';

export const agentApi = {
  async sendMessage(params: {
    case_id: string;
    text: string;
    session_id?: string;
  }): Promise<AgentMessageResponse> {
    const { data } = await apiClient.post<AgentMessageResponse>(
      '/agent/message',
      params
    );
    return data;
  },
};
```

### 4.4 其他 API 模組（auth.ts、schedules.ts、reports.ts、cases.ts）

依後端 endpoint 實作對應方法。Claude Code 對照後端 router 即可。
**重要**：用 TypeScript 嚴格定義所有 request/response 型別，避免 API 變動時前端誤用。

---

## 5. State Management（`src/store/`）

### 5.1 `auth.ts`

```typescript
// src/store/auth.ts
import { create } from 'zustand';
import { User } from '../api/types';
import { secureStorage } from '../utils/secureStorage';
import { apiClient } from '../api/client';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (accessToken: string, refreshToken: string, user: User) => Promise<void>;
  logout: () => Promise<void>;
  loadFromStorage: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

  login: async (accessToken, refreshToken, user) => {
    await secureStorage.setAccessToken(accessToken);
    await secureStorage.setRefreshToken(refreshToken);
    set({ user, isAuthenticated: true, isLoading: false });
  },

  logout: async () => {
    await secureStorage.clearTokens();
    set({ user: null, isAuthenticated: false });
  },

  loadFromStorage: async () => {
    const token = await secureStorage.getAccessToken();
    if (!token) {
      set({ isLoading: false });
      return;
    }
    try {
      const { data } = await apiClient.get<User>('/auth/me');
      set({ user: data, isAuthenticated: true, isLoading: false });
    } catch {
      await secureStorage.clearTokens();
      set({ isLoading: false });
    }
  },
}));
```

### 5.2 `case.ts`

```typescript
// src/store/case.ts
import { create } from 'zustand';
import { Case } from '../api/types';

interface CaseState {
  currentCase: Case | null;
  cases: Case[];
  setCurrentCase: (c: Case) => void;
  setCases: (cs: Case[]) => void;
}

export const useCaseStore = create<CaseState>((set) => ({
  currentCase: null,
  cases: [],
  setCurrentCase: (c) => set({ currentCase: c }),
  setCases: (cs) => set({ cases: cs }),
}));
```

---

## 6. 導覽結構（`src/navigation/`）

### 6.1 `RootNavigator.tsx`

```typescript
// src/navigation/RootNavigator.tsx
import React, { useEffect } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { useAuthStore } from '../store/auth';
import { LoginScreen } from '../screens/LoginScreen';
import { OnboardingScreen } from '../screens/OnboardingScreen';
import { MainTabNavigator } from './MainTabNavigator';
import { EventDetailScreen } from '../screens/EventDetailScreen';
import { ReportPreviewScreen } from '../screens/ReportPreviewScreen';

const Stack = createNativeStackNavigator();

export const RootNavigator = () => {
  const { isAuthenticated, isLoading, loadFromStorage } = useAuthStore();

  useEffect(() => {
    loadFromStorage();
  }, []);

  if (isLoading) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
        <ActivityIndicator size="large" color="#4a6fa5" />
      </View>
    );
  }

  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {!isAuthenticated ? (
          <Stack.Screen name="Login" component={LoginScreen} />
        ) : (
          <>
            <Stack.Screen name="Main" component={MainTabNavigator} />
            <Stack.Screen name="Onboarding" component={OnboardingScreen} />
            <Stack.Screen
              name="EventDetail"
              component={EventDetailScreen}
              options={{ presentation: 'modal' }}
            />
            <Stack.Screen name="ReportPreview" component={ReportPreviewScreen} />
          </>
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
};
```

### 6.2 `MainTabNavigator.tsx`

底部四個 tab，依照 mockup 設計：

```typescript
// src/navigation/MainTabNavigator.tsx
import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Text } from 'react-native';
import { HomeScreen } from '../screens/HomeScreen';
import { ChatScreen } from '../screens/ChatScreen';
import { CalendarScreen } from '../screens/CalendarScreen';
import { RecordsScreen } from '../screens/RecordsScreen';
import { colors } from '../theme/colors';

const Tab = createBottomTabNavigator();

const tabIcon = (icon: string, focused: boolean) => (
  <Text style={{
    fontSize: 18,
    color: focused ? colors.brand.primary : colors.text.tertiary,
  }}>
    {icon}
  </Text>
);

export const MainTabNavigator = () => (
  <Tab.Navigator
    screenOptions={{
      headerShown: false,
      tabBarActiveTintColor: colors.brand.primary,
      tabBarInactiveTintColor: colors.text.tertiary,
      tabBarStyle: {
        height: 60,
        paddingBottom: 8,
        paddingTop: 8,
        borderTopWidth: 0.5,
        borderTopColor: colors.border.light,
      },
      tabBarLabelStyle: { fontSize: 10 },
    }}
  >
    <Tab.Screen
      name="Home"
      component={HomeScreen}
      options={{
        tabBarLabel: '首頁',
        tabBarIcon: ({ focused }) => tabIcon('⌂', focused),
      }}
    />
    <Tab.Screen
      name="Chat"
      component={ChatScreen}
      options={{
        tabBarLabel: 'AI助理',
        tabBarIcon: ({ focused }) => tabIcon('✦', focused),
      }}
    />
    <Tab.Screen
      name="Calendar"
      component={CalendarScreen}
      options={{
        tabBarLabel: '行事曆',
        tabBarIcon: ({ focused }) => tabIcon('▦', focused),
      }}
    />
    <Tab.Screen
      name="Records"
      component={RecordsScreen}
      options={{
        tabBarLabel: '紀錄',
        tabBarIcon: ({ focused }) => tabIcon('⊞', focused),
      }}
    />
  </Tab.Navigator>
);
```

---

## 7. Google OAuth 整合（`src/screens/LoginScreen.tsx`）

```typescript
// src/screens/LoginScreen.tsx
import React, { useEffect } from 'react';
import { View, Text, StyleSheet, Alert } from 'react-native';
import * as WebBrowser from 'expo-web-browser';
import * as AuthSession from 'expo-auth-session';
import { Button } from '../components/ui/Button';
import { apiClient } from '../api/client';
import { useAuthStore } from '../store/auth';
import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';

WebBrowser.maybeCompleteAuthSession();

const API_BASE = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

export const LoginScreen = () => {
  const { login } = useAuthStore();

  const handleGoogleSignIn = async () => {
    try {
      // 1. 後端產生 auth URL
      const { data } = await apiClient.get<{ auth_url: string }>(
        '/auth/google/login'
      );

      // 2. 開啟瀏覽器讓使用者授權
      const result = await WebBrowser.openAuthSessionAsync(
        data.auth_url,
        AuthSession.makeRedirectUri({ scheme: 'coparenting' })
      );

      if (result.type !== 'success') {
        return;
      }

      // 3. callback URL 中含有 code，後端 callback 已處理（直接回傳 token）
      // 由於我們的後端 callback 直接回傳 JSON，這裡需要特殊處理：
      // 方案 A：後端 callback redirect 到 deep link（coparenting://auth?token=...）
      // 方案 B：先完成 web flow，token 存在後端 session，App 用另一個 endpoint 取
      //
      // MVP 採方案 A（後端要改 callback 行為，把 token 編碼進 deep link）
      const url = new URL(result.url);
      const accessToken = url.searchParams.get('access_token');
      const refreshToken = url.searchParams.get('refresh_token');
      const userJson = url.searchParams.get('user');

      if (!accessToken || !refreshToken || !userJson) {
        throw new Error('Auth callback 缺少必要參數');
      }

      const user = JSON.parse(decodeURIComponent(userJson));
      await login(accessToken, refreshToken, user);
    } catch (e: any) {
      Alert.alert('登入失敗', e.message || '請稍後再試');
    }
  };

  return (
    <View style={styles.container}>
      <View style={styles.brandSection}>
        <Text style={styles.logo}>⚖</Text>
        <Text style={styles.title}>共親職排程</Text>
        <Text style={styles.subtitle}>讓共同監護更有條理</Text>
      </View>

      <View style={styles.actionSection}>
        <Button onPress={handleGoogleSignIn} variant="primary">
          使用 Google 帳號登入
        </Button>
        <Text style={styles.hint}>
          首次登入會請您授權 Google Calendar，讓排程自動同步
        </Text>
      </View>

      <Text style={styles.disclaimer}>
        本應用程式不提供法律意見。若需法律諮詢，請洽家事律師。
      </Text>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background.primary,
    padding: spacing.xl,
    justifyContent: 'space-between',
  },
  brandSection: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  logo: { fontSize: 64, marginBottom: spacing.lg },
  title: { ...typography.h1, color: colors.text.primary, marginBottom: spacing.xs },
  subtitle: { ...typography.body, color: colors.text.secondary },
  actionSection: { marginBottom: spacing.xl },
  hint: {
    ...typography.caption,
    color: colors.text.tertiary,
    textAlign: 'center',
    marginTop: spacing.md,
  },
  disclaimer: {
    ...typography.caption,
    color: colors.text.tertiary,
    textAlign: 'center',
    marginBottom: spacing.lg,
  },
});
```

**重要：後端 callback 需要修改**

後端 `auth/google/callback` 目前回傳 JSON。為了讓 App 接收 token，要改成 redirect 到 deep link：

```python
# app/api/v1/auth.py（修改 google_callback）
from fastapi.responses import RedirectResponse
import urllib.parse

@router.get("/google/callback")
async def google_callback(code: str, state: str, ...):
    # ... 原本的邏輯 ...

    # 判斷是 App 還是 Web 呼叫（透過 state 或 user-agent）
    # MVP：一律 redirect 到 deep link
    user_json = urllib.parse.quote(json.dumps({
        "id": str(user.id),
        "display_name": user.display_name,
        "email": user.email,
        "role": user.role,
        "gcal_scope_granted": user.gcal_scope_granted,
    }))

    redirect_url = (
        f"coparenting://auth"
        f"?access_token={access_token}"
        f"&refresh_token={refresh_token}"
        f"&user={user_json}"
    )
    return RedirectResponse(url=redirect_url)
```

`app.json` 的 deep link 設定：
```json
{
  "expo": {
    "scheme": "coparenting",
    ...
  }
}
```

---

## 8. 四個主要畫面

### 8.1 HomeScreen

對照 mockup 第一個畫面，呈現：
- 案件 header（藍色）
- 兩個統計卡（本月我的天數、下次交接）
- 衝突警示條（如果有）
- 「即將到來」事件列表
- 右下角 FAB → 跳到 Chat

```typescript
// src/screens/HomeScreen.tsx
import React, { useEffect } from 'react';
import { View, Text, ScrollView, StyleSheet, TouchableOpacity } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useCaseStore } from '../store/case';
import { schedulesApi } from '../api/schedules';
import { StatCard } from '../components/ui/StatCard';
import { EventCard } from '../components/ui/EventCard';
import { AlertBanner } from '../components/ui/AlertBanner';
import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';

export const HomeScreen = () => {
  const navigation = useNavigation<any>();
  const { currentCase } = useCaseStore();
  const [events, setEvents] = React.useState([]);
  const [stats, setStats] = React.useState({ myDays: 0, totalDays: 0 });

  useEffect(() => {
    if (!currentCase) return;
    loadData();
  }, [currentCase]);

  const loadData = async () => {
    // 取本月事件
    const start = new Date();
    start.setDate(1);
    const end = new Date(start);
    end.setMonth(end.getMonth() + 1);
    end.setDate(0);

    const { items } = await schedulesApi.listEvents(currentCase!.id, start, end);
    setEvents(items);

    // 計算統計
    const myDays = items.filter(e =>
      e.custodian_id === currentCase!.id /* 需比對 user id，這裡是示意 */
    ).length;
    setStats({ myDays, totalDays: items.length });
  };

  if (!currentCase) {
    return <Text>請先建立案件</Text>;
  }

  const upcomingEvents = events.slice(0, 3);

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>{currentCase.case_name}</Text>
        <Text style={styles.headerSubtitle}>共同監護 · 本月剩 11 天</Text>
      </View>

      <ScrollView style={styles.body}>
        <View style={styles.statsRow}>
          <StatCard
            label="本月我的天數"
            value={String(stats.myDays)}
            sub={`共 ${stats.totalDays} 天（${Math.round(stats.myDays / stats.totalDays * 100)}%）`}
          />
          <StatCard
            label="下次交接"
            value="明天 07:30"
            sub="週五 4/25 · 上學日"
            valueSize="small"
          />
        </View>

        <AlertBanner
          icon="⚑"
          text="4/10 排程有重疊，請確認或修改"
        />

        <Text style={styles.sectionLabel}>即將到來</Text>
        {upcomingEvents.map(e => (
          <EventCard
            key={e.id}
            event={e}
            currentUserId={currentCase.id /* 改成實際 user.id */}
            onPress={() => navigation.navigate('EventDetail', { eventId: e.id })}
          />
        ))}

        <View style={{ height: 80 }} />
      </ScrollView>

      <TouchableOpacity
        style={styles.fab}
        onPress={() => navigation.navigate('Chat')}
      >
        <Text style={styles.fabIcon}>✦</Text>
      </TouchableOpacity>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background.tertiary },
  header: {
    backgroundColor: colors.brand.primary,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.lg + 4,
  },
  headerTitle: { ...typography.h2, color: colors.text.inverse, marginBottom: 2 },
  headerSubtitle: {
    ...typography.body,
    color: colors.text.inverse,
    opacity: 0.82,
  },
  body: { flex: 1, padding: spacing.lg },
  statsRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  sectionLabel: {
    ...typography.sectionLabel,
    color: colors.text.tertiary,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  fab: {
    position: 'absolute',
    bottom: 80,
    right: 16,
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.brand.primary,
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: colors.brand.primary,
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.28,
    shadowRadius: 8,
    elevation: 4,
  },
  fabIcon: { fontSize: 22, color: colors.text.inverse },
});
```

### 8.2 ChatScreen

對照 mockup 第二個畫面，重點：
- 訊息泡泡（user 藍底白字、ai 灰底深字）
- AI 訊息可包含「澄清選項按鈕」與「✓ 已建立」綠色框
- 底部輸入列

```typescript
// src/screens/ChatScreen.tsx
import React, { useState, useRef, useEffect } from 'react';
import { View, ScrollView, StyleSheet, KeyboardAvoidingView, Platform } from 'react-native';
import { useCaseStore } from '../store/case';
import { agentApi } from '../api/agent';
import { MessageBubble } from '../components/chat/MessageBubble';
import { ClarifyOptions } from '../components/chat/ClarifyOptions';
import { DoneBox } from '../components/chat/DoneBox';
import { ChatInput } from '../components/chat/ChatInput';
import { colors } from '../theme/colors';

interface ChatMessage {
  id: string;
  role: 'user' | 'ai';
  text: string;
  options?: { label: string }[];
  doneBoxes?: { title: string; details: string[] }[];
  timestamp: string;
}

export const ChatScreen = () => {
  const { currentCase } = useCaseStore();
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: '0',
      role: 'ai',
      text: '您好！請用自然語言描述監護安排，我會幫您自動建立行事曆與法律紀錄。',
      timestamp: new Date().toISOString(),
    },
  ]);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [isSending, setIsSending] = useState(false);
  const scrollRef = useRef<ScrollView>(null);

  const handleSend = async (text: string) => {
    if (!currentCase || !text.trim()) return;

    // 1. 新增 user 訊息到 UI
    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      text,
      timestamp: new Date().toISOString(),
    };
    setMessages(m => [...m, userMsg]);
    setIsSending(true);

    try {
      // 2. 呼叫後端
      const response = await agentApi.sendMessage({
        case_id: currentCase.id,
        text,
        session_id: sessionId,
      });
      setSessionId(response.session_id);

      // 3. 解析回應為 ChatMessage
      const aiMsg: ChatMessage = {
        id: response.session_id + '-' + Date.now(),
        role: 'ai',
        text: response.reply,
        timestamp: new Date().toISOString(),
      };

      if (response.requires_clarification) {
        aiMsg.options = response.clarification_options;
      }

      // 提取「已建立」結果
      const doneBoxes = response.actions_taken
        .filter(a => a.tool.startsWith('create_') && a.result.status === 'created')
        .map(a => ({
          title: a.tool === 'create_recurring_custody_rule'
            ? '✓ 週期規則建立完成'
            : '✓ 單次事件建立完成',
          details: [a.result.summary],
        }));
      if (doneBoxes.length) aiMsg.doneBoxes = doneBoxes;

      setMessages(m => [...m, aiMsg]);
    } catch (e: any) {
      setMessages(m => [...m, {
        id: 'err-' + Date.now(),
        role: 'ai',
        text: '抱歉，處理時發生錯誤，請稍後再試。',
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      setIsSending(false);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 100);
    }
  };

  const handleOptionSelect = (optionLabel: string) => {
    handleSend(optionLabel);
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.header}>
        {/* 與 mockup 一致的藍色 header */}
      </View>

      <ScrollView
        ref={scrollRef}
        style={styles.body}
        contentContainerStyle={{ padding: 14 }}
      >
        {messages.map(msg => (
          <View key={msg.id} style={{ marginBottom: 9 }}>
            <MessageBubble role={msg.role} text={msg.text} timestamp={msg.timestamp} />
            {msg.options && (
              <ClarifyOptions
                options={msg.options}
                onSelect={handleOptionSelect}
              />
            )}
            {msg.doneBoxes?.map((db, i) => (
              <DoneBox key={i} title={db.title} details={db.details} />
            ))}
          </View>
        ))}
      </ScrollView>

      <ChatInput onSend={handleSend} disabled={isSending} />
    </KeyboardAvoidingView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background.primary },
  header: {
    backgroundColor: colors.brand.primary,
    paddingHorizontal: 20,
    paddingTop: 14,
    paddingBottom: 16,
  },
  body: { flex: 1 },
});
```

### 8.3 CalendarScreen

用 `react-native-calendars` 套件，但要客製化日期格的渲染來呈現藍/橘背景：

```typescript
// src/screens/CalendarScreen.tsx
import React, { useState, useEffect } from 'react';
import { View, Text, ScrollView, StyleSheet } from 'react-native';
import { Calendar, DateData } from 'react-native-calendars';
import { useCaseStore } from '../store/case';
import { schedulesApi } from '../api/schedules';
import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import { format } from 'date-fns';
import { zhTW } from 'date-fns/locale';

interface MarkedDate {
  custom: 'me' | 'other' | 'conflict';
}

export const CalendarScreen = () => {
  const { currentCase } = useCaseStore();
  const [markedDates, setMarkedDates] = useState<Record<string, any>>({});
  const [selectedDate, setSelectedDate] = useState<string>('');
  const [eventsOnDate, setEventsOnDate] = useState([]);

  useEffect(() => {
    if (!currentCase) return;
    loadMonth(new Date());
  }, [currentCase]);

  const loadMonth = async (date: Date) => {
    const start = new Date(date.getFullYear(), date.getMonth(), 1);
    const end = new Date(date.getFullYear(), date.getMonth() + 1, 0);

    const { items } = await schedulesApi.listEvents(currentCase!.id, start, end);

    const marked: Record<string, any> = {};
    items.forEach(event => {
      const dateKey = format(new Date(event.starts_at), 'yyyy-MM-dd');
      const isMine = event.custodian_id === /* user id */ '';
      marked[dateKey] = {
        customStyles: {
          container: {
            backgroundColor: isMine
              ? colors.brand.primaryLight
              : colors.counterparty.primaryLight,
            borderRadius: 8,
          },
          text: {
            color: isMine
              ? colors.brand.primaryAccent
              : colors.counterparty.primaryAccent,
            fontWeight: '500',
          },
        },
      };
    });
    setMarkedDates(marked);
  };

  return (
    <View style={styles.container}>
      <Calendar
        markingType="custom"
        markedDates={markedDates}
        onDayPress={(day: DateData) => {
          setSelectedDate(day.dateString);
          // 載入當日事件
        }}
        theme={{
          calendarBackground: colors.background.primary,
          textSectionTitleColor: colors.text.tertiary,
          monthTextColor: colors.text.primary,
          arrowColor: colors.brand.primary,
          todayTextColor: colors.brand.primary,
        }}
      />

      <View style={styles.legend}>
        <LegendItem color={colors.brand.primaryLight} label="我監護" />
        <LegendItem color={colors.counterparty.primaryLight} label="對方監護" />
        <LegendItem color={colors.conflict.cellBackground} label="需確認" />
      </View>

      <ScrollView style={styles.eventList}>
        <Text style={styles.eventListTitle}>
          {selectedDate ? `${selectedDate} 的事件` : '4 月 20 日起'}
        </Text>
        {/* 事件列表 */}
      </ScrollView>
    </View>
  );
};

const LegendItem = ({ color, label }: { color: string; label: string }) => (
  <View style={legendStyles.item}>
    <View style={[legendStyles.dot, { backgroundColor: color }]} />
    <Text style={legendStyles.text}>{label}</Text>
  </View>
);

const legendStyles = StyleSheet.create({
  item: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  dot: { width: 10, height: 10, borderRadius: 3 },
  text: { ...typography.caption, color: colors.text.secondary },
});

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background.primary },
  legend: {
    flexDirection: 'row',
    gap: spacing.md,
    padding: spacing.md,
    borderTopWidth: 0.5,
    borderTopColor: colors.border.light,
  },
  eventList: { flex: 1, padding: spacing.md },
  eventListTitle: {
    ...typography.caption,
    color: colors.text.tertiary,
    marginBottom: spacing.sm,
  },
});
```

### 8.4 RecordsScreen

對照 mockup 第四個畫面，呈現接送紀錄與「產生 PDF 報告」按鈕。

```typescript
// src/screens/RecordsScreen.tsx
import React, { useState, useEffect } from 'react';
import { View, Text, ScrollView, StyleSheet, Alert } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useCaseStore } from '../store/case';
import { reportsApi } from '../api/reports';
import { Button } from '../components/ui/Button';
import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';

export const RecordsScreen = () => {
  const navigation = useNavigation<any>();
  const { currentCase } = useCaseStore();
  const [records, setRecords] = useState([]);
  const [generating, setGenerating] = useState(false);

  // 載入本月紀錄
  useEffect(() => {
    // 從 schedulesApi.listEvents + handover_records 組合
  }, [currentCase]);

  const handleGenerateReport = async () => {
    if (!currentCase) return;
    setGenerating(true);
    try {
      const today = new Date();
      const periodStart = new Date(today.getFullYear(), today.getMonth(), 1);
      const periodEnd = new Date(today.getFullYear(), today.getMonth() + 1, 0);

      const report = await reportsApi.create({
        case_id: currentCase.id,
        period_start: periodStart,
        period_end: periodEnd,
        report_type: 'monthly',
      });

      navigation.navigate('ReportPreview', { reportId: report.id });
    } catch (e: any) {
      Alert.alert('產生失敗', e.message);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>接送紀錄</Text>
        <Text style={styles.headerSub}>
          {format(new Date(), 'M 月')} · 具法律效力
        </Text>
      </View>

      <ScrollView style={styles.body}>
        <Text style={styles.sectionLabel}>本月紀錄</Text>

        {records.map(r => (
          <RecordItem key={r.id} record={r} />
        ))}

        <View style={{ alignItems: 'center', marginTop: spacing.lg }}>
          <Button
            onPress={handleGenerateReport}
            variant="primary"
            disabled={generating}
          >
            {generating ? '產生中…' : '產生本月 PDF 報告'}
          </Button>
        </View>
      </ScrollView>
    </View>
  );
};
```

---

## 9. 共用元件實作要點

### 9.1 `Button.tsx`

```typescript
// src/components/ui/Button.tsx
import React from 'react';
import { TouchableOpacity, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { colors } from '../../theme/colors';
import { spacing, radius } from '../../theme/spacing';
import { typography } from '../../theme/typography';

interface Props {
  onPress: () => void;
  variant?: 'primary' | 'secondary';
  disabled?: boolean;
  loading?: boolean;
  children: string;
}

export const Button = ({ onPress, variant = 'primary', disabled, loading, children }: Props) => (
  <TouchableOpacity
    onPress={onPress}
    disabled={disabled || loading}
    style={[
      styles.base,
      variant === 'primary' ? styles.primary : styles.secondary,
      (disabled || loading) && styles.disabled,
    ]}
    activeOpacity={0.8}
  >
    {loading ? (
      <ActivityIndicator color={variant === 'primary' ? colors.text.inverse : colors.brand.primary} />
    ) : (
      <Text style={[
        styles.text,
        variant === 'primary' ? styles.textPrimary : styles.textSecondary,
      ]}>
        {children}
      </Text>
    )}
  </TouchableOpacity>
);

const styles = StyleSheet.create({
  base: {
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 44,
  },
  primary: { backgroundColor: colors.brand.primary },
  secondary: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: colors.brand.primary,
  },
  disabled: { opacity: 0.5 },
  text: { ...typography.bodyMedium },
  textPrimary: { color: colors.text.inverse },
  textSecondary: { color: colors.brand.primary },
});
```

### 9.2 其他元件

依照 mockup 的視覺實作：
- `StatCard`：兩欄統計卡（淺灰底、圓角 10）
- `EventCard`：事件卡片（左側 3px 色條，藍色=我、橘色=對方）
- `Pill`：小標籤（「我」、「對方」）
- `AlertBanner`：黃色衝突警示
- `MessageBubble`：對話泡泡（user 藍底白字、ai 灰底深字）
- `ClarifyOptions`：澄清選項按鈕（藍框白底）
- `DoneBox`：「✓ 已建立」綠色提示框

每個元件寫成獨立 file，props 用 TypeScript interface 定義。

---

## 10. 環境變數設定

### 10.1 `.env`（本地開發）

```
EXPO_PUBLIC_API_URL=http://10.0.2.2:8000/api/v1
# Android 模擬器用 10.0.2.2，iOS 模擬器用 localhost，實機要用區網 IP
```

### 10.2 `.env.production`

```
EXPO_PUBLIC_API_URL=https://your-cloud-run-url/api/v1
```

### 10.3 `app.json` 重點設定

```json
{
  "expo": {
    "name": "共親職排程",
    "slug": "coparenting",
    "scheme": "coparenting",
    "version": "1.0.0",
    "orientation": "portrait",
    "ios": {
      "bundleIdentifier": "com.yourcompany.coparenting",
      "supportsTablet": false
    },
    "android": {
      "package": "com.yourcompany.coparenting",
      "intentFilters": [
        {
          "action": "VIEW",
          "category": ["DEFAULT", "BROWSABLE"],
          "data": [{ "scheme": "coparenting" }]
        }
      ]
    },
    "plugins": [
      "expo-secure-store"
    ]
  }
}
```

---

## 11. DoD（完成標準）

### 11.1 環境驗證

```bash
cd mobile
npm install
npx expo start
# 用 Expo Go App 掃 QR code，或按 a 開 Android 模擬器、i 開 iOS
```

### 11.2 功能驗收劇本

**劇本一：登入與初次使用**
- [ ] 開啟 App 看到登入畫面
- [ ] 點「使用 Google 登入」開啟瀏覽器
- [ ] 完成 Google 授權後自動回到 App，顯示首頁
- [ ] 首次登入若無案件，導向 Onboarding 建案件

**劇本二:Home → Chat → 建立排程**
- [ ] 首頁顯示統計卡與即將到來事件
- [ ] 點右下 FAB 跳到 Chat
- [ ] 輸入「我每週一三五帶小孩」
- [ ] AI 回覆「已建立規則」（DoneBox 顯示）

**劇本三：Chat → 澄清流程**
- [ ] 輸入「我這個月一三五週帶小孩」
- [ ] AI 顯示澄清選項按鈕
- [ ] 點「每週的週一、三、五」
- [ ] AI 確認並建立規則

**劇本四：行事曆檢視**
- [ ] 進入 Calendar tab
- [ ] 月檢視顯示藍色（我）和橘色（對方）的日期
- [ ] 點某天顯示當日事件清單
- [ ] 上下切換月份正常

**劇本五：產生 PDF 報告**
- [ ] 進入 Records tab
- [ ] 看到本月接送紀錄列表
- [ ] 點「產生本月 PDF 報告」
- [ ] PDF 預覽畫面顯示，可分享/儲存

**劇本六：登出與重登**
- [ ] 設定頁登出
- [ ] 回到登入畫面
- [ ] 重新登入後資料正常顯示

### 11.3 視覺驗收

對照 mockup 確認：
- [ ] 顏色一致（藍 #4a6fa5、橘 #c87941）
- [ ] 底部四個 tab，順序：首頁、AI 助理、行事曆、紀錄
- [ ] FAB 位於右下，藍色圓形
- [ ] 字級層級清楚（h1 22px、h2 17px、body 13px）
- [ ] 中文字型不模糊（Android 確認）

### 11.4 跨平台驗收

- [ ] iOS 模擬器跑通完整劇本
- [ ] Android 模擬器跑通完整劇本
- [ ] 實機（至少一台）跑通登入 + Chat 流程

---

## 12. 給 Claude Code 的注意事項

1. **後端 OAuth callback 必須改**：本文件 §7 提到的 deep link redirect 是必要修改，否則 App 收不到 token。先改後端再實作 LoginScreen。

2. **`react-native-calendars` 的客製化**：原生套件預設樣式不符合 mockup，要用 `markingType="custom"` 配合 `customStyles` 才能做出整格背景色的效果。文件範例已示範。

3. **`expo-secure-store` 的 key size 限制**：Android 上單一 value 上限 2KB，refresh token 通常很長要先用 base64 縮短（其實 JWT 本身就是 base64 了，沒問題）。

4. **deep link 的 scheme**：開發時 Expo Go 的 scheme 是 `exp://`，需要在 `app.json` 設定 `scheme: "coparenting"` 才能用自訂 scheme。本機測試用 `npx uri-scheme open coparenting://auth?... --android` 模擬。

5. **Android 模擬器的 localhost**：若後端跑在本機 docker，Android 模擬器要用 `10.0.2.2:8000` 才能連到，不是 `localhost`。iOS 模擬器可以直接用 `localhost`。

6. **TypeScript 嚴格模式**：`tsconfig.json` 啟用 `"strict": true`，所有 API response 都要先過 type guard 再使用。

7. **State 不要直接從 AsyncStorage 讀**：所有持久化都透過 `useAuthStore.loadFromStorage()`，避免 component 各自呼叫造成 race condition。

8. **不要在 ChatScreen 用 FlatList**：訊息數量少（單次對話 < 30 條），ScrollView 比較簡單且不會有 keyExtractor 問題。Phase 2 訊息歷史多了再優化。

9. **錯誤處理**：所有 API 呼叫都要 try/catch，失敗時用 `Alert.alert` 顯示。Phase 2 換成 toast 元件。

10. **不要做的事**:不要實作即時 push 通知（Phase 2）、不要做 offline mode（Phase 2）、不要實作家長雙方協作 UI（Phase 2）。MVP 聚焦於單方使用者完整流程。

---

## 13. 預估開發時間

| 階段 | 工時 |
|---|---|
| 專案初始化 + 設計系統 | 1 天 |
| API client + state | 1 天 |
| 登入 + Onboarding | 1.5 天 |
| HomeScreen | 1 天 |
| ChatScreen（最複雜） | 2 天 |
| CalendarScreen | 1.5 天 |
| RecordsScreen + PDF preview | 1 天 |
| 共用元件打磨 | 1 天 |
| 跨平台測試與修 bug | 2 天 |
| **合計** | **約 11–12 天** |

---

## 14. Phase 1 完成後的下一步

完成 M1.8 後，Phase 1 正式結束，使用者可以：
- 登入
- 用自然語言建立排程
- 在行事曆上看到自己 vs 對方的監護分佈
- 產生具有稽核完整性的 PDF 報告

接下來進入 **Phase 2**，主要工作：
- 雙方協作（邀請對方加入、規則修改需雙方確認）
- LINE Messaging API 推送通知
- 接送打卡（GPS + 照片）
- 爭議紀錄與進階報告

Phase 2 完成後，產品就有完整的雙邊協作能力，可以開始小規模 beta 測試。
