import React, { useState } from 'react';
import {
  Modal, View, Text, TextInput, TouchableOpacity,
  StyleSheet, Platform, KeyboardAvoidingView,
} from 'react-native';
import { colors } from '../../theme/colors';
import { spacing, radius } from '../../theme/spacing';
import { typography } from '../../theme/typography';

interface Props {
  visible: boolean;
  date: string;        // "2026-06-07"
  onClose: () => void;
  onSave: (startsAt: string, endsAt: string, notes: string) => Promise<void>;
}

const pad = (n: number) => String(n).padStart(2, '0');

const parseTime = (val: string): { h: number; m: number } | null => {
  const m = val.match(/^(\d{1,2}):(\d{2})$/);
  if (!m) return null;
  const h = parseInt(m[1]), min = parseInt(m[2]);
  if (h < 0 || h > 23 || min < 0 || min > 59) return null;
  return { h, m: min };
};

export const AddEventModal = ({ visible, date, onClose, onSave }: Props) => {
  const [startTime, setStartTime] = useState('09:00');
  const [endTime, setEndTime] = useState('17:00');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleSave = async () => {
    setError('');
    const s = parseTime(startTime);
    const e = parseTime(endTime);
    if (!s) { setError('開始時間格式錯誤（請輸入 HH:MM）'); return; }
    if (!e) { setError('結束時間格式錯誤（請輸入 HH:MM）'); return; }
    if (e.h * 60 + e.m <= s.h * 60 + s.m) { setError('結束時間須晚於開始時間'); return; }

    const tzOffset = '+08:00';
    const startsAt = `${date}T${pad(s.h)}:${pad(s.m)}:00${tzOffset}`;
    const endsAt = `${date}T${pad(e.h)}:${pad(e.m)}:00${tzOffset}`;

    setSaving(true);
    try {
      await onSave(startsAt, endsAt, notes);
      setStartTime('09:00');
      setEndTime('17:00');
      setNotes('');
      onClose();
    } catch {
      setError('儲存失敗，請再試一次');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={styles.overlay}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <View style={styles.sheet}>
          <Text style={styles.title}>新增排程</Text>
          <Text style={styles.dateLabel}>{date}</Text>

          <Text style={styles.label}>開始時間（HH:MM）</Text>
          <TextInput
            style={styles.input}
            value={startTime}
            onChangeText={setStartTime}
            placeholder="09:00"
            keyboardType="numbers-and-punctuation"
            maxLength={5}
          />

          <Text style={styles.label}>結束時間（HH:MM）</Text>
          <TextInput
            style={styles.input}
            value={endTime}
            onChangeText={setEndTime}
            placeholder="17:00"
            keyboardType="numbers-and-punctuation"
            maxLength={5}
          />

          <Text style={styles.label}>備註（選填）</Text>
          <TextInput
            style={[styles.input, styles.inputMulti]}
            value={notes}
            onChangeText={setNotes}
            placeholder="例：學校運動會"
            multiline
            numberOfLines={2}
          />

          {error ? <Text style={styles.error}>{error}</Text> : null}

          <View style={styles.buttons}>
            <TouchableOpacity style={styles.btnCancel} onPress={onClose}>
              <Text style={styles.btnCancelText}>取消</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.btnSave, saving && styles.btnDisabled]}
              onPress={handleSave}
              disabled={saving}
            >
              <Text style={styles.btnSaveText}>{saving ? '儲存中...' : '儲存'}</Text>
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0,0,0,0.4)',
  },
  sheet: {
    backgroundColor: colors.background.primary,
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    padding: spacing.lg,
    paddingBottom: spacing.xl,
  },
  title: { ...typography.h2, color: colors.text.primary, marginBottom: spacing.xs },
  dateLabel: { ...typography.body, color: colors.brand.primary, marginBottom: spacing.md },
  label: { ...typography.captionMedium, color: colors.text.secondary, marginBottom: spacing.xs, marginTop: spacing.sm },
  input: {
    borderWidth: 1,
    borderColor: colors.border.light,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    ...typography.body,
    color: colors.text.primary,
  },
  inputMulti: { height: 64, textAlignVertical: 'top' },
  error: { ...typography.caption, color: 'red', marginTop: spacing.sm },
  buttons: { flexDirection: 'row', gap: spacing.md, marginTop: spacing.lg },
  btnCancel: {
    flex: 1, padding: spacing.md, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border.light, alignItems: 'center',
  },
  btnCancelText: { ...typography.body, color: colors.text.secondary },
  btnSave: {
    flex: 1, padding: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.brand.primary, alignItems: 'center',
  },
  btnDisabled: { opacity: 0.5 },
  btnSaveText: { ...typography.body, color: colors.text.inverse },
});
