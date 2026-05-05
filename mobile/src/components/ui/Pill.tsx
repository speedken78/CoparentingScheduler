import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors } from '../../theme/colors';
import { spacing, radius } from '../../theme/spacing';
import { typography } from '../../theme/typography';

interface Props {
  type: 'me' | 'other';
}

export const Pill = ({ type }: Props) => (
  <View style={[styles.base, type === 'me' ? styles.me : styles.other]}>
    <Text style={[styles.text, type === 'me' ? styles.textMe : styles.textOther]}>
      {type === 'me' ? '我' : '對方'}
    </Text>
  </View>
);

const styles = StyleSheet.create({
  base: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.pill,
  },
  me: { backgroundColor: colors.brand.primaryLight },
  other: { backgroundColor: colors.counterparty.primaryLight },
  text: { ...typography.captionMedium },
  textMe: { color: colors.brand.primaryAccent },
  textOther: { color: colors.counterparty.primaryAccent },
});
