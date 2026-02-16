import { SidebarTrigger } from '@/components/ui/sidebar';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useTerm } from '@/contexts/TermContext';
import { Plus, Sun, Moon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import AddTermDialog from '@/components/shared/AddTermDialog';
import { useState } from 'react';
import { useTheme } from '@/contexts/ThemeContext';

export function AppHeader() {
  const { currentTerm, setCurrentTerm, terms } = useTerm();
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b bg-background px-4">
      {/* Sidebar Toggle Button */}
      <SidebarTrigger className="-ml-1" />

      {/* Spacer */}
      <div className="flex-1" />

      {/* Global Term Selector */}
      <div className="flex items-center gap-2">
        <Select value={currentTerm} onValueChange={setCurrentTerm}>
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
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setIsDialogOpen(true)}>
            <Plus className="h-4 w-4" />
          </Button>
          <AddTermDialog open={isDialogOpen} onOpenChange={setIsDialogOpen} />
          <Button variant="ghost" size="sm" onClick={toggleTheme} aria-label="Toggle theme">
            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </header>
  );
}

