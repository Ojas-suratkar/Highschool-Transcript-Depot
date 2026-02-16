import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

export type ValueType = 'grade' | 'marks' | 'gpa';

interface ValueTypeSelectorProps {
  valueType: ValueType;
  onValueTypeChange: (type: ValueType) => void;
  value: string;
  onValueChange: (value: string) => void;
  className?: string;
}

const gradeOptions = [
  'A+', 'A', 'A-',
  'B+', 'B', 'B-',
  'C+', 'C', 'C-',
  'D+', 'D', 'D-',
  'F'
];

export function ValueTypeSelector({
  valueType,
  onValueTypeChange,
  value,
  onValueChange,
  className,
}: ValueTypeSelectorProps) {
  return (
    <div className={className}>
      <ToggleGroup
        type="single"
        value={valueType}
        onValueChange={(v) => v && onValueTypeChange(v as ValueType)}
        className="justify-start mb-2"
      >
        <ToggleGroupItem value="grade" aria-label="Grade">
          Grade
        </ToggleGroupItem>
        <ToggleGroupItem value="marks" aria-label="Marks">
          Marks
        </ToggleGroupItem>
        <ToggleGroupItem value="gpa" aria-label="GPA">
          GPA
        </ToggleGroupItem>
      </ToggleGroup>

      {valueType === 'grade' && (
        <Select value={value} onValueChange={onValueChange}>
          <SelectTrigger>
            <SelectValue placeholder="Select grade" />
          </SelectTrigger>
          <SelectContent>
            {gradeOptions.map((grade) => (
              <SelectItem key={grade} value={grade}>
                {grade}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      {valueType === 'marks' && (
        <Input
          type="number"
          placeholder="0-100"
          value={value}
          onChange={(e) => onValueChange(e.target.value)}
          min="0"
          max="100"
        />
      )}

      {valueType === 'gpa' && (
        <Input
          type="number"
          placeholder="0.0-4.0"
          value={value}
          onChange={(e) => onValueChange(e.target.value)}
          min="0"
          max="4"
          step="0.1"
        />
      )}
    </div>
  );
}

