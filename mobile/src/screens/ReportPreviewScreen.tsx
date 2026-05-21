import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Alert, Share } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { WebView } from 'react-native-webview';
import { reportsApi } from '../api/reports';
import { Report } from '../api/types';
import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import { format } from 'date-fns';

export const ReportPreviewScreen = () => {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const { reportId, caseId } = route.params as { reportId: string; caseId: string };
  const [report, setReport] = useState<Report | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);

  useEffect(() => {
    loadReport();
  }, [reportId]);

  const loadReport = async () => {
    try {
      const list = await reportsApi.list(caseId);
      const found = list.find(r => r.id === reportId);
      if (found) setReport(found);
      const dataUri = await reportsApi.downloadPdfBase64(caseId, reportId);
      setDownloadUrl(dataUri);
    } catch (e: any) {
      Alert.alert('載入失敗', e.message);
    }
  };

  const handleShare = async () => {
    await Share.share({ message: '共親職監護報告 PDF（稽核雜湊：' + (report?.pdf_sha256?.slice(0, 16) ?? '') + '…）' });
  };

  return (
    <View style={styles.container}>
      <View style={styles.topBar}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Text style={styles.backIcon}>‹</Text>
        </TouchableOpacity>
        <Text style={styles.topTitle}>PDF 報告</Text>
        <TouchableOpacity onPress={handleShare} disabled={!downloadUrl} style={styles.shareBtn}>
          <Text style={[styles.shareText, !downloadUrl && styles.disabled]}>分享</Text>
        </TouchableOpacity>
      </View>

      {report && (
        <View style={styles.meta}>
          <Text style={styles.metaText}>
            產生時間：{format(new Date(report.generated_at), 'yyyy/MM/dd HH:mm')}
          </Text>
          <Text style={styles.metaText} numberOfLines={1}>
            SHA-256：{report.pdf_sha256.slice(0, 16)}…
          </Text>
        </View>
      )}

      {downloadUrl ? (
        <WebView
          source={{ uri: downloadUrl }}
          style={styles.webview}
          startInLoadingState
        />
      ) : (
        <View style={styles.loadingBox}>
          <Text style={styles.loadingText}>載入 PDF 中…</Text>
        </View>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background.primary },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xl,
    paddingBottom: spacing.md,
    borderBottomWidth: 0.5,
    borderBottomColor: colors.border.light,
  },
  backBtn: { width: 36, height: 36, justifyContent: 'center' },
  backIcon: { fontSize: 24, color: colors.brand.primary },
  topTitle: { ...typography.h3, color: colors.text.primary },
  shareBtn: { paddingHorizontal: spacing.sm },
  shareText: { ...typography.bodyMedium, color: colors.brand.primary },
  disabled: { opacity: 0.4 },
  meta: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    backgroundColor: colors.background.secondary,
    borderBottomWidth: 0.5,
    borderBottomColor: colors.border.light,
  },
  metaText: { ...typography.caption, color: colors.text.tertiary },
  webview: { flex: 1 },
  loadingBox: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  loadingText: { ...typography.body, color: colors.text.tertiary },
});
