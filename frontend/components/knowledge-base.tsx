"use client";

import { useRef, useState } from "react";
import { Upload, Trash2, FileText, Loader2, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Loader } from "@/components/prompt-kit/loader";
import { formatTime, cn } from "@/lib/utils";
import type { PaperFile } from "@/lib/types";

type KnowledgeBaseProps = {
  files: PaperFile[];
  isLoading: boolean;
  isUploading: boolean;
  error: string | null;
  onUpload: (files: File[]) => void;
  onDelete: (fileId: string) => void;
};

type PaperStatus =
  | { label: string; variant: "wave" | "pulse"; done: false }
  | { label: string; variant: null; done: true };

function getPaperStatus(file: PaperFile): PaperStatus {
  if (file.is_indexed === 1) return { label: "已入库", variant: null, done: true };
  if (file.is_md_parsed === 1) return { label: "构建索引中", variant: "pulse", done: false };
  return { label: "解析中", variant: "wave", done: false };
}

export function KnowledgeBase({
  files,
  isLoading,
  isUploading,
  error,
  onUpload,
  onDelete,
}: KnowledgeBaseProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) {
      onUpload(Array.from(e.target.files));
      e.target.value = "";
    }
  };

  const handleDelete = (fileId: string) => {
    setPendingDelete(fileId);
    onDelete(fileId);
    setPendingDelete(null);
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <header className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <h1 className="truncate text-sm font-medium">知识库</h1>
        <Button
          variant="outline"
          size="sm"
          className="gap-2"
          onClick={() => inputRef.current?.click()}
          disabled={isUploading}
        >
          {isUploading ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Upload className="size-4" />
          )}
          上传文件
        </Button>
        <input
          type="file"
          ref={inputRef}
          onChange={handleFileChange}
          className="hidden"
          multiple
          accept=".txt,.pdf"
        />
      </header>

      {error && (
        <div className="border-b border-destructive/20 bg-destructive/5 px-4 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-16 animate-pulse rounded-lg bg-muted"
              />
            ))}
          </div>
        ) : files.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-20 text-muted-foreground">
            <FileText className="size-12 opacity-40" />
            <p className="text-sm">暂无文件，点击右上角上传论文</p>
          </div>
        ) : (
          <ul className="space-y-2">
            {files.map((file) => {
              const status = getPaperStatus(file);
              return (
                <li
                  key={file.file_id}
                  className="group flex items-center gap-3 rounded-lg border p-3 transition-colors hover:bg-muted/50"
                >
                  <FileText className="size-5 shrink-0 text-primary" />
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="truncate text-sm font-medium">
                      {file.file_name}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {formatTime(file.upload_time)}
                    </span>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <Check className={cn("size-3.5 text-green-500", !status.done && "hidden")} />
                    <Loader variant={status.variant ?? "wave"} size="sm" className={cn(status.done && "hidden")} />
                    <span className="text-xs text-muted-foreground">
                      {status.label}
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                    onClick={() => handleDelete(file.file_id)}
                    disabled={pendingDelete === file.file_id}
                    title="删除文件"
                  >
                    {pendingDelete === file.file_id ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Trash2 className="text-destructive" />
                    )}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
