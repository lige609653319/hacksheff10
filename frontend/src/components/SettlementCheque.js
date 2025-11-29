import React from 'react';

export const SettlementCheque = ({ transaction }) => {
  const formatCurrency = (amount) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(amount);
  };

  return (
    <div className="relative w-full max-w-xl mx-auto bg-white border border-stone-300 rounded-sm shadow-md overflow-hidden transform transition-all hover:-translate-y-1 hover:shadow-lg mb-6">
      {/* Decorative left strip */}
      <div className="absolute left-0 top-0 bottom-0 w-12 bg-indigo-900 flex flex-col items-center justify-center text-indigo-200 border-r border-dashed border-indigo-700">
        <span className="transform -rotate-90 tracking-widest text-xs font-bold uppercase whitespace-nowrap">
          TripWise Settlement
        </span>
      </div>

      <div className="pl-16 pr-6 py-6 font-serif">
        <div className="flex justify-between items-start mb-6">
          <div className="text-stone-500 text-xs tracking-wider uppercase">Official Remittance</div>
          <div className="text-right">
             <div className="bg-indigo-50 text-indigo-900 px-3 py-1 border border-indigo-200 rounded font-bold text-lg">
               {formatCurrency(transaction.amount)}
             </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="flex items-baseline border-b border-stone-300 pb-1">
            <span className="text-stone-400 text-xs font-sans uppercase w-20 flex-shrink-0">Pay To</span>
            <span className="text-xl text-indigo-950 font-bold flex-grow ml-2">{transaction.to}</span>
          </div>

          <div className="flex items-baseline border-b border-stone-300 pb-1">
            <span className="text-stone-400 text-xs font-sans uppercase w-20 flex-shrink-0">From</span>
            <span className="text-lg text-stone-700 flex-grow ml-2">{transaction.from}</span>
          </div>
          
          <div className="flex items-baseline border-b border-stone-300 pb-1">
             <span className="text-stone-400 text-xs font-sans uppercase w-20 flex-shrink-0">Memo</span>
             <span className="text-sm text-stone-500 italic ml-2">Trip expense settlement</span>
          </div>
        </div>
      </div>
      
      {/* Watermark effect */}
      <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 text-9xl text-indigo-50 font-serif font-bold opacity-30 pointer-events-none select-none z-0">
        PAID
      </div>
    </div>
  );
};


