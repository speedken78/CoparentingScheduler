import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Platform, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { HomeScreen } from '../screens/HomeScreen';
import { ChatScreen } from '../screens/ChatScreen';
import { CalendarScreen } from '../screens/CalendarScreen';
import { RecordsScreen } from '../screens/RecordsScreen';
import { colors } from '../theme/colors';
import { MainTabParamList } from './types';

const Tab = createBottomTabNavigator<MainTabParamList>();

const tabIcon = (icon: string, focused: boolean) => (
  <Text style={{ fontSize: 18, color: focused ? colors.brand.primary : colors.text.tertiary }}>
    {icon}
  </Text>
);

export const MainTabNavigator = () => {
  const insets = useSafeAreaInsets();

  return (
  <Tab.Navigator
    screenOptions={{
      headerShown: false,
      tabBarActiveTintColor: colors.brand.primary,
      tabBarInactiveTintColor: colors.text.tertiary,
      tabBarStyle: {
        height: 60 + insets.bottom,
        paddingBottom: insets.bottom + 8,
        paddingTop: 8,
        borderTopWidth: 0.5,
        borderTopColor: colors.border.light,
      },
      tabBarLabelStyle: { fontSize: 10 },
      tabBarHideOnKeyboard: Platform.OS === 'android',
    }}
  >
    <Tab.Screen
      name="Home"
      component={HomeScreen}
      options={{ tabBarLabel: '首頁', tabBarIcon: ({ focused }) => tabIcon('⌂', focused) }}
    />
    <Tab.Screen
      name="Chat"
      component={ChatScreen}
      options={{ tabBarLabel: 'AI助理', tabBarIcon: ({ focused }) => tabIcon('✦', focused) }}
    />
    <Tab.Screen
      name="Calendar"
      component={CalendarScreen}
      options={{ tabBarLabel: '行事曆', tabBarIcon: ({ focused }) => tabIcon('▦', focused) }}
    />
    <Tab.Screen
      name="Records"
      component={RecordsScreen}
      options={{ tabBarLabel: '紀錄', tabBarIcon: ({ focused }) => tabIcon('⊞', focused) }}
    />
  </Tab.Navigator>
  );
};
