import React, { useState } from 'react';
import { View, Text, TextInput, StyleSheet, Alert, ScrollView } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { casesApi } from '../api/cases';
import { useCaseStore } from '../store/case';
import { Button } from '../components/ui/Button';
import { colors } from '../theme/colors';
import { spacing, radius } from '../theme/spacing';
import { typography } from '../theme/typography';

export const OnboardingScreen = () => {
  const navigation = useNavigation<any>();
  const { setCurrentCase } = useCaseStore();
  const [caseName, setCaseName] = useState('');
  const [custodyType, setCustodyType] = useState<'sole' | 'joint' | 'split'>('joint');
  const [loading, setLoading] = useState(false);

  const handleCreate = async () => {
    if (!caseName.trim()) {
      Alert.alert('請填寫案件名稱');
      return;
    }
    setLoading(true);
    try {
      const newCase = await casesApi.create({
        case_name: caseName.trim(),
        custody_type: custodyType,
        timezone: 'Asia/Taipei',
      });
      setCurrentCase(newCase);
      navigation.replace('Main');
    } catch (e: any) {
      Alert.alert('建立失敗', e.message || '請稍後再試');
    } finally {
      setLoading(false);
    }
  };

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>建立第一個案件</Text>
        <Text style={styles.subtitle}>之後可以在設定中修改</Text>
      </View>

      <View style={styles.form}>
        <Text style={styles.label}>案件名稱</Text>
        <TextInput
          style={styles.input}
          value={caseName}
          onChangeText={setCaseName}
          placeholder="例：王小明監護案"
          placeholderTextColor={colors.text.tertiary}
        />

        <Text style={[styles.label, { marginTop: spacing.lg }]}>監護類型</Text>
        {(['joint', 'sole', 'split'] as const).map(type => (
          <View key={type} style={styles.radioRow}>
            <View style={[styles.radio, custodyType === type && styles.radioSelected]} />
            <Text
              style={styles.radioLabel}
              onPress={() => setCustodyType(type)}
            >
              {type === 'joint' ? '共同監護' : type === 'sole' ? '單獨監護' : '分割監護'}
            </Text>
          </View>
        ))}
      </View>

      <Button onPress={handleCreate} variant="primary" loading={loading}>
        建立並開始使用
      </Button>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: colors.background.primary },
  container: { padding: spacing.xl, paddingTop: spacing.xxl * 2 },
  header: { marginBottom: spacing.xxl },
  title: { ...typography.h1, color: colors.text.primary, marginBottom: spacing.xs },
  subtitle: { ...typography.body, color: colors.text.secondary },
  form: { marginBottom: spacing.xxl },
  label: { ...typography.captionMedium, color: colors.text.tertiary, marginBottom: spacing.xs },
  input: {
    ...typography.body,
    color: colors.text.primary,
    backgroundColor: colors.background.secondary,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border.light,
  },
  radioRow: { flexDirection: 'row', alignItems: 'center', marginBottom: spacing.sm },
  radio: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 2,
    borderColor: colors.brand.primary,
    marginRight: spacing.sm,
  },
  radioSelected: { backgroundColor: colors.brand.primary },
  radioLabel: { ...typography.body, color: colors.text.primary },
});
