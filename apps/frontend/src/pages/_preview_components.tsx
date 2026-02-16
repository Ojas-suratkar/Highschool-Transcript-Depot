import AddTermDialog from '@/components/shared/AddTermDialog';
import { ExtractedDataDialog } from '@/components/dialogs/ExtractedDataDialog';
import { ManualEntryDialog } from '@/components/dialogs/ManualEntryDialog';
import PdfPreviewDialog from '@/components/dialogs/PdfPreviewDialog';
import { ReviewAndTrainDialog } from '@/components/dialogs/ReviewAndTrainDialog';
import TranscriptDetailDialog from '@/components/dialogs/TranscriptDetailDialog';
import { ViewStudentDialog } from '@/components/dialogs/ViewStudentDialog';
import { TermProvider } from '@/contexts/TermContext';

export default function ComponentPreviewPage() {
  const sampleProcessedTranscript = {
    id: 't-123',
    studentName: 'Alex Morgan',
    school: 'Central High',
    gpa: 3.78,
    courses: 5,
    templateUsed: 'Central HS - V1',
    extractedData: {
      gpa: 3.78,
      graduationDate: '2024-05-15',
      courses: [
        { name: 'Algebra II', grade: 'A', credits: 4 },
        { name: 'English Lit', grade: 'B+', credits: 4 },
        { name: 'Biology', grade: 'A-', credits: 3 },
      ],
    },
  };

  const sampleTranscriptRecord = {
    id: 't-123',
    studentName: 'Alex Morgan',
    email: 'alex@example.com',
    format: 'Central HS - V1',
    birthDate: '2006-02-10',
    graduationDate: '2024-05-15',
    address: '123 Main St',
    courses: [
      { name: 'Algebra II', grade: 'A', credits: '4' },
      { name: 'English Lit', grade: 'B+', credits: '4' },
    ],
    gpa: '3.78',
    marks: '865/1000',
    processed: 1,
  };

  const sampleFormat = {
    id: 'f-1',
    studentName: 'Alex Morgan',
    school: 'Central High',
    detected: 'detected-pdf.png',
    detectedDate: '2024-01-01',
    status: 'new',
  };

  return (
    <div style={{ padding: 20 }}>
      <h1>Component previews</h1>

      <section style={{ margin: '20px 0' }}>
        <h2>AddTermDialog (open)</h2>
        <TermProvider>
          <AddTermDialog open={true} onOpenChange={() => {}} />
        </TermProvider>
      </section>

      <section style={{ margin: '20px 0' }}>
        <h2>ExtractedDataDialog (open)</h2>
        <ExtractedDataDialog open={true} onOpenChange={() => {}} transcript={sampleProcessedTranscript} />
      </section>

      <section style={{ margin: '20px 0' }}>
        <h2>ManualEntryDialog (open)</h2>
        <ManualEntryDialog open={true} onOpenChange={() => {}} transcript={{ id: 't-123', studentName: 'Alex Morgan', email: 'alex@example.com', school: 'Central High', gpa: 3.78 }} />
      </section>

      <section style={{ margin: '20px 0' }}>
        <h2>PdfPreviewDialog (open)</h2>
        <PdfPreviewDialog open={true} onOpenChange={() => {}} title="Preview" idLabel="doc-1" />
      </section>

      <section style={{ margin: '20px 0' }}>
        <h2>ReviewAndTrainDialog (open)</h2>
        <ReviewAndTrainDialog open={true} onOpenChange={() => {}} format={sampleFormat} onAssignTemplate={() => {}} />
      </section>

      <section style={{ margin: '20px 0' }}>
        <h2>TranscriptDetailDialog (open)</h2>
        <TranscriptDetailDialog open={true} onOpenChange={() => {}} transcript={sampleTranscriptRecord} />
      </section>

      <section style={{ margin: '20px 0' }}>
        <h2>ViewStudentDialog (open)</h2>
        <ViewStudentDialog open={true} onOpenChange={() => {}} transcript={{ id: 't-123', studentName: 'Alex Morgan', uploadDate: '2024-01-10', status: 'processed', gpa: 3.78, school: 'Central High', email: 'alex@example.com' }} />
      </section>
    </div>
  );
}
