declare module "*.css";

interface NDEFRecordInit {
  recordType: string;
  data?: string | BufferSource;
  mediaType?: string;
  id?: string;
}
interface NDEFMessageInit {
  records: NDEFRecordInit[];
}
interface NDEFRecordRead {
  recordType: string;
  data?: DataView;
}
interface NDEFReadingEvent extends Event {
  serialNumber: string;
  message: { records: ReadonlyArray<NDEFRecordRead> };
}
declare class NDEFReader extends EventTarget {
  constructor();
  onreading: ((this: NDEFReader, ev: NDEFReadingEvent) => unknown) | null;
  onreadingerror: ((this: NDEFReader, ev: Event) => unknown) | null;
  scan(options?: { signal?: AbortSignal }): Promise<void>;
  write(message: string | BufferSource | NDEFMessageInit, options?: { overwrite?: boolean; signal?: AbortSignal }): Promise<void>;
  makeReadOnly?(options?: { signal?: AbortSignal }): Promise<void>;
}
