import { sendForm } from "./client";

export interface UploadReceiptResponse {
  file_id: string;
}

export function uploadReceipt(
  orderId: string,
  file: File,
): Promise<UploadReceiptResponse> {
  const form = new FormData();
  form.append("file", file, file.name);
  return sendForm<UploadReceiptResponse>(
    "POST",
    `/orders/${encodeURIComponent(orderId)}/receipt`,
    form,
  );
}
