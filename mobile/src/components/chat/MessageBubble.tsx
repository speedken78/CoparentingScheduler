import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors } from '../../theme/colors';
import { spacing, radius } from '../../theme/spacing';
import { typography } from '../../theme/typography';
import { formatEventTime } from '../../utils/formatDate';

interface Props {
  role: 'user' | 'ai';
  text: string;
  timestamp: string;
}

export const MessageBubble = ({ role, text, timestamp }: Props) => {
  const isUser = role === 'user';
  return (
    <View style={[styles.wrapper, isUser ? styles.wrapperUser : styles.wrapperAi]}>
      {!isUser && <Text style={styles.aiLabel}>AI 助理</Text>}
      <View style={[styles.bubble, isUser ? styles.bubbleUser : styles.bubbleAi]}>
        <Text style={[styles.text, isUser ? styles.textUser : styles.textAi]}>{text}</Text>
      </View>
      <Text style={[styles.time, isUser ? styles.timeUser : styles.timeAi]}>
        {formatEventTime(timestamp)}
      </Text>
    </View>
  );
};

const styles = StyleSheet.create({
  wrapper: { maxWidth: '80%' },
  wrapperUser: { alignSelf: 'flex-end', alignItems: 'flex-end' },
  wrapperAi: { alignSelf: 'flex-start', alignItems: 'flex-start' },
  aiLabel: { ...typography.captionMedium, color: colors.brand.primary, marginBottom: 3 },
  bubble: {
    borderRadius: radius.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  bubbleUser: { backgroundColor: colors.brand.primary },
  bubbleAi: { backgroundColor: colors.background.secondary },
  text: { ...typography.bodyLarge },
  textUser: { color: colors.text.inverse },
  textAi: { color: colors.text.primary },
  time: { ...typography.caption, marginTop: 2 },
  timeUser: { color: colors.text.tertiary },
  timeAi: { color: colors.text.tertiary },
});
