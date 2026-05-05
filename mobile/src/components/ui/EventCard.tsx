import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { CustodyEvent } from '../../api/types';
import { colors } from '../../theme/colors';
import { spacing, radius } from '../../theme/spacing';
import { typography } from '../../theme/typography';
import { formatEventDate, formatEventTime } from '../../utils/formatDate';
import { Pill } from './Pill';

interface Props {
  event: CustodyEvent;
  currentUserId: string;
  onPress: () => void;
}

export const EventCard = ({ event, currentUserId, onPress }: Props) => {
  const isMe = event.custodian_id === currentUserId;
  return (
    <TouchableOpacity style={styles.card} onPress={onPress} activeOpacity={0.8}>
      <View style={[styles.stripe, isMe ? styles.stripeMe : styles.stripeOther]} />
      <View style={styles.content}>
        <View style={styles.row}>
          <Text style={styles.date}>{formatEventDate(event.starts_at)}</Text>
          <Pill type={isMe ? 'me' : 'other'} />
        </View>
        <Text style={styles.time}>
          {formatEventTime(event.starts_at)}–{formatEventTime(event.ends_at)}
        </Text>
        {event.notes && <Text style={styles.notes} numberOfLines={1}>{event.notes}</Text>}
      </View>
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    backgroundColor: colors.background.card,
    borderRadius: radius.md,
    marginBottom: spacing.sm,
    overflow: 'hidden',
    borderWidth: 0.5,
    borderColor: colors.border.light,
  },
  stripe: { width: 3 },
  stripeMe: { backgroundColor: colors.brand.primary },
  stripeOther: { backgroundColor: colors.counterparty.primary },
  content: { flex: 1, padding: spacing.md },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2 },
  date: { ...typography.bodyMedium, color: colors.text.primary },
  time: { ...typography.body, color: colors.text.secondary },
  notes: { ...typography.caption, color: colors.text.tertiary, marginTop: 2 },
});
