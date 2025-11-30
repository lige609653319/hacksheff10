import React, { useState } from 'react';
import { API_URL } from '../config';

export const JsonImport = ({ onImport }) => {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleFetchFromServer = async () => {
    setIsLoading(true);
    setError(null);

    try {
      // Fetch bills from backend API
      const response = await fetch(`${API_URL}/api/bills?page=1&per_page=100`);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      
      // Convert backend bill format to Expense format
      // Backend returns { success: true, data: bills, pagination: {...} }
      const bills = result.data || [];
      const expenses = bills.map(bill => ({
        id: bill.id.toString(),
        description: bill.topic || '',
        amount: bill.amount || 0,
        payer: bill.payer || '',
        sharedBy: typeof bill.participants === 'string' 
          ? JSON.parse(bill.participants) 
          : (bill.participants || []),
        date: bill.created_at || new Date().toISOString()
      }));

      if (expenses.length === 0) {
        setError("No expenses found on server.");
      } else {
        onImport(expenses);
      }
    } catch (err) {
      console.error('Fetch error:', err);
      setError("Failed to fetch data from the server. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="bg-white/90 backdrop-blur rounded-lg p-6 shadow-sm border border-indigo-100">
      <h3 className="text-lg font-bold text-indigo-900 mb-2">Sync Trip Data</h3>
      <p className="text-sm text-stone-600 mb-4">
        Retrieve the latest shared expenses from the server to update the settlement plan.
      </p>
      
      <button
        onClick={handleFetchFromServer}
        disabled={isLoading}
        className="w-full flex items-center justify-center space-x-2 py-4 border-2 border-indigo-500 border-dashed rounded-lg bg-indigo-50 hover:bg-indigo-100 text-indigo-700 font-medium transition-all disabled:opacity-50 disabled:cursor-wait active:scale-[0.99]"
      >
        {isLoading ? (
          <>
            <svg className="animate-spin h-5 w-5 text-indigo-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <span>Syncing from Server...</span>
          </>
        ) : (
          <>
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
            <span>Load Expenses from Server</span>
          </>
        )}
      </button>

      {error && (
        <div className="mt-3 p-2 bg-red-50 text-red-600 text-xs rounded border border-red-200">
          Error: {error}
        </div>
      )}
    </div>
  );
};

