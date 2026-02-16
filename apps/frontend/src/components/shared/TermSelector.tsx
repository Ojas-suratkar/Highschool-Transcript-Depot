import { useState } from 'react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import AddTermDialog from './AddTermDialog';
import { Plus } from 'lucide-react';
import { useTerm } from '@/contexts/TermContext';

interface TermSelectorProps {
  value: string;
  onValueChange: (value: string) => void;
  label?: string;
  showAddButton?: boolean;
}

export function TermSelector({ value, onValueChange, label = 'Term', showAddButton = true }: TermSelectorProps) {
  const { terms } = useTerm();
  const [isDialogOpen, setIsDialogOpen] = useState(false);

  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <div className="flex gap-2">
        <Select value={value} onValueChange={onValueChange}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Select term" />
          </SelectTrigger>
          <SelectContent>
            {terms.map((term) => (
              <SelectItem key={term.id} value={term.id}>
                {term.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {showAddButton && (
          <>
            <Button variant="outline" size="icon" onClick={() => setIsDialogOpen(true)}>
              <Plus className="h-4 w-4" />
            </Button>
            <AddTermDialog open={isDialogOpen} onOpenChange={setIsDialogOpen} />
          </>
        )}
      </div>

  {/* AddTermDialog is rendered next to the add button above */}
    </div>
  );
}

