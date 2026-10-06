export type DetectedPerson = {
  box: { x: number; y: number; width: number; height: number };
  confidence: number;
  identity: string | null;
  identity_confidence: number | null;
  is_intruder: boolean;
};

export type DetectionSnapshot = {
  analyzed_at: string;
  has_intruder: boolean;
  people: DetectedPerson[];
};
