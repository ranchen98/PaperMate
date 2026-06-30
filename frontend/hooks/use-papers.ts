"use client";

import { useCallback, useEffect, useState } from "react";
import { deletePaper, fetchPapers, uploadPapers } from "@/lib/api";
import type { PaperFile } from "@/lib/types";

export function usePapers(enabled: boolean = true) {
  const [files, setFiles] = useState<PaperFile[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await fetchPapers();
      setFiles(list);
      return list;
    } catch (err) {
      console.error("[usePapers] refresh error:", err);
      setError(err instanceof Error ? err.message : "加载文件列表失败");
      return [];
    }
  }, []);

  const loadInitial = useCallback(async () => {
    setIsLoading(true);
    await refresh();
    setIsLoading(false);
  }, [refresh]);

  useEffect(() => {
    if (!enabled) {
      setIsLoading(false);
      return;
    }
    loadInitial();
  }, [enabled, loadInitial]);

  const upload = useCallback(
    async (newFiles: File[]) => {
      if (newFiles.length === 0) return;
      setIsUploading(true);
      setError(null);
      try {
        await uploadPapers(newFiles);
        await refresh();
      } catch (err) {
        console.error("[usePapers] upload error:", err);
        setError(err instanceof Error ? err.message : "上传失败");
      } finally {
        setIsUploading(false);
      }
    },
    [refresh],
  );

  const remove = useCallback(
    async (fileId: string) => {
      setError(null);
      try {
        await deletePaper(fileId);
        setFiles((prev) => prev.filter((f) => f.file_id !== fileId));
      } catch (err) {
        console.error("[usePapers] delete error:", err);
        setError(err instanceof Error ? err.message : "删除失败");
      }
    },
    [],
  );

  return {
    files,
    isLoading,
    isUploading,
    error,
    refresh,
    upload,
    remove,
  };
}
