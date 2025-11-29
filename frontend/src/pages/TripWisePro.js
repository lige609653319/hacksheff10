import React, { useState, useMemo } from 'react';
import { TabView } from '../types';
import { SettlementCheque } from '../components/SettlementCheque';
import { JsonImport } from '../components/JsonImport';

// Initial Data (Empty)
const INITIAL_PARTICIPANTS = [];
const INITIAL_EXPENSES = [];

const TripWisePro = () => {
  // --- State ---
  const [participants, setParticipants] = useState(INITIAL_PARTICIPANTS);
  const [expenses, setExpenses] = useState(INITIAL_EXPENSES);
  const [activeTab, setActiveTab] = useState(TabView.EXPENSES);
  
  // Form State
  const [newExpenseDesc, setNewExpenseDesc] = useState('');
  const [newExpenseAmount, setNewExpenseAmount] = useState('');
  const [newExpensePayer, setNewExpensePayer] = useState('');
  const [newExpenseSharedBy, setNewExpenseSharedBy] = useState([]);
  
  const [newParticipantName, setNewParticipantName] = useState('');

  // --- Calculations ---

  const { transactions } = useMemo(() => {
    // 1. Calculate Balances
    const balMap = {};
    participants.forEach(p => balMap[p] = 0);

    expenses.forEach(exp => {
      const amount = exp.amount;
      const payer = exp.payer;
      const sharedBy = exp.sharedBy;
      
      // Ensure payer exists in map (handle imported data case)
      if (balMap[payer] === undefined) balMap[payer] = 0;

      // Payer gets credit for full amount
      balMap[payer] += amount;

      // Split cost
      if (sharedBy.length > 0) {
        const splitAmount = amount / sharedBy.length;
        sharedBy.forEach(person => {
          if (balMap[person] === undefined) balMap[person] = 0;
          balMap[person] -= splitAmount;
        });
      }
    });

    const calculatedBalances = Object.entries(balMap).map(([participant, amount]) => ({
      participant,
      amount
    }));

    // 2. Simplify Settlements (Greedy Algorithm)
    const settlements = [];
    let debtors = calculatedBalances.filter(b => b.amount < -0.01).sort((a, b) => a.amount - b.amount); // Ascending (most negative first)
    let creditors = calculatedBalances.filter(b => b.amount > 0.01).sort((a, b) => b.amount - a.amount); // Descending (most positive first)

    let dIndex = 0;
    let cIndex = 0;

    while (dIndex < debtors.length && cIndex < creditors.length) {
      const debtor = debtors[dIndex];
      const creditor = creditors[cIndex];

      const debtAmount = Math.abs(debtor.amount);
      const creditAmount = creditor.amount;

      const settlementAmount = Math.min(debtAmount, creditAmount);

      settlements.push({
        from: debtor.participant,
        to: creditor.participant,
        amount: settlementAmount
      });

      // Adjust remaining
      debtor.amount += settlementAmount;
      creditor.amount -= settlementAmount;

      // Move indices if settled
      if (Math.abs(debtor.amount) < 0.01) dIndex++;
      if (creditor.amount < 0.01) cIndex++;
    }

    return { balances: calculatedBalances, transactions: settlements };
  }, [expenses, participants]);

  // --- Handlers ---

  const handleAddParticipant = () => {
    if (newParticipantName.trim() && !participants.includes(newParticipantName.trim())) {
      const newName = newParticipantName.trim();
      setParticipants(prev => [...prev, newName]);
      
      // Update form defaults if this is the first participant
      if (participants.length === 0) {
        setNewExpensePayer(newName);
      }
      
      // Add new person to shared list by default for convenience
      setNewExpenseSharedBy(prev => [...prev, newName]);
      
      setNewParticipantName('');
    }
  };

  const handleDeleteParticipant = (name) => {
    // Check if participant is involved in any expenses
    const isInvolved = expenses.some(e => e.payer === name || e.sharedBy.includes(name));
    
    if (isInvolved) {
      alert(`Cannot delete ${name} because they are part of existing expenses. Please delete those expenses first.`);
      return;
    }

    const updatedParticipants = participants.filter(p => p !== name);
    setParticipants(updatedParticipants);
    
    // Remove from form state
    setNewExpenseSharedBy(prev => prev.filter(p => p !== name));
    if (newExpensePayer === name) {
      setNewExpensePayer(updatedParticipants[0] || '');
    }
  };

  const handleAddExpense = (e) => {
    e.preventDefault();
    if (!newExpenseDesc || !newExpenseAmount || newExpenseSharedBy.length === 0 || !newExpensePayer) return;

    const expense = {
      id: Date.now().toString(),
      description: newExpenseDesc,
      amount: parseFloat(newExpenseAmount),
      payer: newExpensePayer,
      sharedBy: newExpenseSharedBy,
      date: new Date().toISOString()
    };

    setExpenses([...expenses, expense]);
    setNewExpenseDesc('');
    setNewExpenseAmount('');
    // Reset SharedBy to all participants for convenience
    setNewExpenseSharedBy(participants);
  };

  const handleDeleteExpense = (id) => {
    setExpenses(expenses.filter(e => e.id !== id));
  };

  const handleJsonImport = (importedExpenses) => {
    // Extract unique participants from the imported data to update participant list
    const newParticipantsSet = new Set(participants);
    importedExpenses.forEach(exp => {
      newParticipantsSet.add(exp.payer);
      exp.sharedBy.forEach(s => newParticipantsSet.add(s));
    });
    
    const newParticipantsList = Array.from(newParticipantsSet);
    setParticipants(newParticipantsList);
    setExpenses(importedExpenses);
    
    // Update form state defaults
    if (newParticipantsList.length > 0) {
      setNewExpensePayer(newParticipantsList[0]);
      setNewExpenseSharedBy(newParticipantsList);
    }

    // Auto-switch to settlements to show the "magic"
    setActiveTab(TabView.SETTLEMENTS);
  };

  const toggleShareParticipant = (name) => {
    if (newExpenseSharedBy.includes(name)) {
      setNewExpenseSharedBy(newExpenseSharedBy.filter(n => n !== name));
    } else {
      setNewExpenseSharedBy([...newExpenseSharedBy, name]);
    }
  };

  const formatMoney = (val) => {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val);
  };

  // --- Render Helpers ---

  const renderExpenseForm = () => (
    <div className="bg-white rounded-xl shadow-lg p-6 border border-stone-100">
      <h3 className="text-xl font-bold text-indigo-900 mb-4 flex items-center">
        <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4"></path></svg>
        Add Expense
      </h3>
      {participants.length === 0 ? (
        <div className="text-center py-6 text-stone-500 bg-stone-50 rounded-lg border border-dashed border-stone-200">
          Add participants below to start tracking expenses.
        </div>
      ) : (
        <form onSubmit={handleAddExpense} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-stone-600 mb-1">Description</label>
            <input 
              type="text" 
              className="w-full px-4 py-2 rounded-lg border border-stone-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all outline-none"
              placeholder="e.g. Dinner at Mario's"
              value={newExpenseDesc}
              onChange={e => setNewExpenseDesc(e.target.value)}
              required
            />
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-stone-600 mb-1">Amount ($)</label>
              <input 
                type="number" 
                step="0.01"
                min="0"
                className="w-full px-4 py-2 rounded-lg border border-stone-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all outline-none"
                placeholder="0.00"
                value={newExpenseAmount}
                onChange={e => setNewExpenseAmount(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-stone-600 mb-1">Paid By</label>
              <select 
                className="w-full px-4 py-2 rounded-lg border border-stone-300 focus:ring-2 focus:ring-indigo-500 outline-none bg-white"
                value={newExpensePayer}
                onChange={e => setNewExpensePayer(e.target.value)}
                required
              >
                {participants.map(p => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-stone-600 mb-2">Split Amongst</label>
            <div className="flex flex-wrap gap-2">
              {participants.map(p => (
                <button
                  key={p}
                  type="button"
                  onClick={() => toggleShareParticipant(p)}
                  className={`px-3 py-1 text-sm rounded-full border transition-colors ${
                    newExpenseSharedBy.includes(p)
                      ? 'bg-indigo-600 text-white border-indigo-600'
                      : 'bg-white text-stone-500 border-stone-300 hover:bg-stone-50'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
            {newExpenseSharedBy.length === 0 && <p className="text-xs text-red-500 mt-1">Select at least one person.</p>}
          </div>

          <button 
            type="submit" 
            disabled={!newExpenseDesc || !newExpenseAmount || newExpenseSharedBy.length === 0}
            className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-lg shadow-md transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Add Expense
          </button>
        </form>
      )}
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col font-sans">
      
      {/* Header */}
      <header className="bg-white border-b border-indigo-100 sticky top-0 z-30 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
           <div className="flex items-center space-x-2">
             <div className="bg-indigo-600 p-2 rounded-lg">
               <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
             </div>
             <span className="text-xl font-serif font-bold text-indigo-900 tracking-tight">TripWise Pro</span>
           </div>

           <nav className="flex space-x-1 bg-stone-100 p-1 rounded-lg">
             {[
               { id: TabView.EXPENSES, label: 'Expenses' },
               { id: TabView.SETTLEMENTS, label: 'Settlements' },
             ].map(tab => (
               <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                  activeTab === tab.id 
                    ? 'bg-white text-indigo-700 shadow-sm' 
                    : 'text-stone-500 hover:text-stone-700'
                }`}
               >
                 {tab.label}
               </button>
             ))}
           </nav>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-grow">
        
        {/* === TAB: EXPENSES === */}
        {activeTab === TabView.EXPENSES && (
          <div className="relative">
            {/* Cool Travel Background Header for Bill Splitter */}
            <div className="h-64 w-full bg-cover bg-center relative" style={{ backgroundImage: 'url("https://picsum.photos/1200/400?grayscale&blur=2")' }}>
               <div className="absolute inset-0 bg-indigo-900/60 backdrop-blur-sm"></div>
               <div className="absolute inset-0 flex flex-col items-center justify-center text-white px-4">
                  <h1 className="text-3xl md:text-4xl font-serif font-bold mb-2">Trip Expenses</h1>
                  <p className="text-indigo-200 text-sm md:text-base max-w-lg text-center">Manage shared costs effortlessly. Add expenses, import data, and let us handle the math.</p>
               </div>
            </div>

            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 -mt-16 pb-20 relative z-10">
               <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                 
                 {/* Left Column: Form & Participants */}
                 <div className="space-y-6">
                    {renderExpenseForm()}

                    {/* Participants Manager */}
                    <div className="bg-white rounded-xl shadow-md p-6 border border-stone-100">
                      <h4 className="font-bold text-indigo-900 mb-3">Participants</h4>
                      
                      {participants.length === 0 ? (
                        <p className="text-sm text-stone-400 italic mb-4">No participants yet.</p>
                      ) : (
                        <div className="flex flex-wrap gap-2 mb-4">
                          {participants.map(p => (
                            <span key={p} className="inline-flex items-center pl-3 pr-1 py-1 rounded-full bg-stone-100 text-stone-700 text-sm border border-stone-200 group">
                              {p}
                              <button 
                                onClick={() => handleDeleteParticipant(p)}
                                className="ml-1 p-1 text-stone-400 hover:text-red-500 hover:bg-red-50 rounded-full transition-colors"
                                title="Remove participant"
                              >
                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                              </button>
                            </span>
                          ))}
                        </div>
                      )}

                      <div className="flex gap-2">
                        <input 
                          type="text" 
                          placeholder="New name..."
                          className="flex-1 px-3 py-2 rounded-lg border border-stone-300 text-sm outline-none focus:border-indigo-500"
                          value={newParticipantName}
                          onChange={e => setNewParticipantName(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && handleAddParticipant()}
                        />
                        <button 
                          onClick={handleAddParticipant}
                          disabled={!newParticipantName.trim()}
                          className="bg-stone-800 text-white px-4 py-2 rounded-lg text-sm hover:bg-stone-900 disabled:opacity-50"
                        >
                          Add
                        </button>
                      </div>
                    </div>

                    {/* Import Module */}
                    <JsonImport onImport={handleJsonImport} />
                 </div>

                 {/* Right Column: List */}
                 <div className="lg:col-span-2 space-y-6">
                    
                    {/* Stats Cards */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                       <div className="bg-white p-6 rounded-xl shadow-sm border border-indigo-50 flex items-center justify-between">
                          <div>
                            <p className="text-stone-500 text-sm">Total Trip Cost</p>
                            <p className="text-2xl font-bold text-indigo-900">{formatMoney(expenses.reduce((acc, curr) => acc + curr.amount, 0))}</p>
                          </div>
                          <div className="bg-indigo-100 p-3 rounded-full text-indigo-600">
                            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                          </div>
                       </div>
                       <div className="bg-white p-6 rounded-xl shadow-sm border border-indigo-50 flex items-center justify-between">
                          <div>
                            <p className="text-stone-500 text-sm">Total Expenses</p>
                            <p className="text-2xl font-bold text-stone-800">{expenses.length}</p>
                          </div>
                          <div className="bg-stone-100 p-3 rounded-full text-stone-600">
                             <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"></path></svg>
                          </div>
                       </div>
                    </div>

                    <div className="bg-white rounded-xl shadow-sm border border-stone-200 overflow-hidden">
                      <div className="px-6 py-4 border-b border-stone-100 bg-stone-50 flex justify-between items-center">
                        <h3 className="font-bold text-stone-700">Recent Transactions</h3>
                        <span className="text-xs text-stone-400">{expenses.length} entries</span>
                      </div>
                      <div className="divide-y divide-stone-100 max-h-[600px] overflow-y-auto">
                        {expenses.length === 0 ? (
                           <div className="p-8 text-center text-stone-400 italic">No expenses added yet.</div>
                        ) : (
                          expenses.slice().reverse().map((expense) => (
                            <div key={expense.id} className="p-4 hover:bg-stone-50 transition-colors flex items-center justify-between group">
                              <div className="flex items-start space-x-3">
                                <div className="bg-indigo-100 text-indigo-700 w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0">
                                  {expense.payer.charAt(0)}
                                </div>
                                <div>
                                  <p className="font-medium text-stone-800">{expense.description}</p>
                                  <p className="text-xs text-stone-500">
                                    <span className="font-semibold">{expense.payer}</span> paid for {expense.sharedBy.length} people
                                  </p>
                                </div>
                              </div>
                              <div className="flex items-center space-x-4">
                                <span className="font-bold text-stone-800">{formatMoney(expense.amount)}</span>
                                <button 
                                  onClick={() => handleDeleteExpense(expense.id)}
                                  className="text-stone-300 hover:text-red-500 transition-colors p-1"
                                >
                                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                                </button>
                              </div>
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                 </div>
               </div>
            </div>
          </div>
        )}

        {/* === TAB: SETTLEMENTS === */}
        {activeTab === TabView.SETTLEMENTS && (
          <div className="max-w-4xl mx-auto px-4 py-10 space-y-10">
             
             <div className="text-center mb-8">
               <h2 className="text-3xl font-serif font-bold text-indigo-900 mb-2">Settlement Plan</h2>
               {transactions.length === 0 ? (
                 <p className="text-stone-500">No settlements pending.</p>
               ) : (
                 <p className="text-stone-500">The most efficient way to settle all debts in {transactions.length} transaction{transactions.length !== 1 ? 's' : ''}.</p>
               )}
             </div>

             {/* Cheques */}
             <div className="space-y-6">
               {transactions.length === 0 ? (
                 <div className="text-center py-20 bg-white rounded-xl border border-dashed border-stone-300">
                    <svg className="w-16 h-16 text-green-500 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                    <p className="text-xl text-stone-600 font-medium">All settled up!</p>
                    <p className="text-stone-400 text-sm">No debts found between participants.</p>
                 </div>
               ) : (
                 transactions.map((t, idx) => (
                   <SettlementCheque key={idx} transaction={t} />
                 ))
               )}
             </div>
          </div>
        )}
      </main>
    </div>
  );
};

export default TripWisePro;


