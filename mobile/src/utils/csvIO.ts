import { Platform } from "react-native";
import * as Sharing from "expo-sharing";
import * as FileSystem from "expo-file-system/legacy";
import * as DocumentPicker from "expo-document-picker";
import { api } from "@/src/api";

// Download/share a CSV produced by a backend export endpoint (returns {filename, content, count}).
export async function exportCsv(path: string) {
  const res = await api.get(path);
  const { filename, content } = res;
  if (Platform.OS === "web") {
    if (typeof document !== "undefined") {
      const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    }
    return res;
  }
  const uri = `${FileSystem.cacheDirectory}${filename}`;
  await FileSystem.writeAsStringAsync(uri, content, { encoding: FileSystem.EncodingType.UTF8 });
  if (await Sharing.isAvailableAsync()) {
    await Sharing.shareAsync(uri, { mimeType: "text/csv", dialogTitle: `Export ${filename}`, UTI: "public.comma-separated-values-text" });
  }
  return res;
}

// Pick a CSV file and POST its text to a backend import endpoint (returns {created, updated, skipped, errors}).
export async function importCsv(path: string) {
  const picked = await DocumentPicker.getDocumentAsync({
    type: ["text/csv", "text/comma-separated-values", "application/csv", "application/vnd.ms-excel", "text/plain", "*/*"],
    copyToCacheDirectory: true,
    multiple: false,
  });
  if (picked.canceled || !picked.assets?.[0]) return null;
  const asset: any = picked.assets[0];
  let text = "";
  if (Platform.OS === "web") {
    if (asset.file && typeof asset.file.text === "function") text = await asset.file.text();
    else text = await fetch(asset.uri).then((r) => r.text());
  } else {
    text = await FileSystem.readAsStringAsync(asset.uri, { encoding: FileSystem.EncodingType.UTF8 });
  }
  if (!text.trim()) throw new Error("The selected file was empty.");
  return await api.post(path, { csv: text });
}
