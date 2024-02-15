import openai
import numpy as np
from orion.evaluation.point import point_accuracy, point_f1_score 
from collections import Counter

with open("openai_api_key.txt", "r") as f:
    api_key = f.read()
    
def load_system_prompt(file_path):
    with open(file_path) as f:
        system_prompt = f.read()
    return system_prompt

GPT_model = "gpt-3.5-turbo" #"gpt-4"

client = openai.Client(api_key=api_key)

def get_model_response(message, gpt_model=GPT_model):
    completion = client.chat.completions.create(
    model=gpt_model,
    messages=message,
    )
    return completion.choices[0].message.content

def create_message_zero_shot(seq_query, system_prompt_file='system_prompt_zero_shot.txt'):
    messages = []
    
    messages.append({"role": "system", "content":load_system_prompt(system_prompt_file)})

    # final prompt
    messages.append({"role": "user", "content": f"Sequence: {seq_query}"})
    return messages


def create_message_one_shot(seq_query, seq_ex, ano_ind_ex, system_prompt_file='system_prompt_one_shot.txt'):
    messages = []
    
    messages.append({"role": "system", "content":load_system_prompt(system_prompt_file)})

    # one shot
    messages.append({"role": "user", "content": f"Sequence: {seq_ex}"})
    messages.append({"role": "assistant", "content": ano_ind_ex})

    # final prompt
    messages.append({"role": "user", "content": f"Sequence: {seq_query}"})
    return messages

def signal_to_str(sequence, start, stop, space = True, digit_round = 2):
    """
    Truncate, round and turn the sequence into array of int, 
    then transform into string
    
    Args: 
        sequence (pandas series): signal 
        start (int): the start index
        stop (int): the end index
        space (bool, default True): True if want to add space between digits, False otherwise
        digit_round (int, default 2): how many digits to round the sequence
    Returns: 
        String of signal
    """
    l_1 = (np.round(sequence.iloc[start:stop].value, digit_round)*(10**digit_round)).astype(int)
    l_2 = l_1 - min(l_1)
    res = ''
    for s in l_2: 
        for d in str(s): 
            res += d
            if space:
                res += ' '
        res += ', '
    return res

def indices_to_str(start, stop, space = True):
    """
    Create a string of indices
    
    Args: 
        start (int): the start index 
        stop (int): the end index
        space (bool, default True): True if want to add space between digits, False otherwise
    Returns: 
        String of indices
    """
    l = range(start, stop+1)
    res = ''
    for s in l: 
        for d in str(s): 
            res += d
            if space:
                res += ' '
        res += ', '
    return res

def LLMresponse_to_list(answer, start, stop):
    """
    Transform output from LLM into list of indices
    
    Args: 
        answer (str): LLM response
        start (int): start index of truncated signal
        stop (int): stop index of truncated signal 
    Returns: 
        List of anomalous indices corresponding to the original signal
    """
    #Remove all characters from answer except the digits and ,
    ans = ''.join(i for i in answer if (i.isdigit() or i == ','))
    
    #remove the extra comma at the end
    if ans[-1] == ",": 
        ans = ans[:-1]
    in_list = ans.split(",")
    ind_list = [int(i) for i in in_list]
    
    #remove indices that exceed the length of signal
    signal_length = stop - start + 1
    ind_list = [i for i in ind_list if i < signal_length]
    
    #convert index of the truncated list back to the index of original signal 
    ind_list = [i + start for i in ind_list]
    
    return ind_list

def get_final_anomalous_list(res_list, threshold = 1): 
    """
    Get the final list of anomalous indices from multiple LLM responses
    
    Args:
        res_list (list of list of int): list of lists of anomous indices output by LLM 
        threshold (int): how many votes an index need to have to be included in final list
    Returns: 
        List of final anomalous indices
    """
    combine_list = [i for l in res_list for i in l]
    cnt = Counter(combine_list)
    return [k for k, v in cnt.items() if v >= threshold]

def indices_to_timestamp(sequence, ind_list): 
    """
    Transform list of indices into list of timestamp
    
    Args: 
        sequence (pandas series): signal
        ind_list (list of int): list of indices
    Returns: 
        List of timestamps
    """
    return sequence.iloc[ind_list].timestamp.to_list()

def evaluate(ground_truth, anomalies, start, end): 
    """
    Evaluate accuracy and f-1 score 
    
    Args: 
        ground_truth (list of timestamps): true anomalies
        anomalies (list of timestamps): detected anamalies
        start (timestamp): start of signal
        end (timestamp): end of signal
    Returns: 
        Accuracy and F-1 score
    """
    return {"accuracy": point_accuracy(ground_truth, anomalies, start=start, end=end), 
            "f-1 score": point_f1_score(ground_truth, anomalies, start=start, end=end)}

def rolling_LLM_prediction(signal, size, step, create_message_func = create_message_zero_shot,
                           space = True, digit_round = 2, threshold = 1, num_iters = 1): 
    """
    Truncate the signal into rolling windows and get LLM response for each window
    
    Args:
        signal (pandas series): signal to detect anomalies
        size (int): size of rolling window
        step (int): step of rolling
        num_iters (int): number of iteration to run LLM model on each window
        create_message_func (func): function to create message for LLM
    Returns:
        List of lists of anomalous indices
    """
    combine_res = []
    
    #Rolling windows truncate
    for start in range(0, len(signal)-size, step): 
        stop = start + size
        trunc_signal_str = signal_to_str(signal, start, stop, digit_round = digit_round, space = space)
        m = create_message_func(trunc_signal_str)
        
        #Get num_iters anomaly predictions
        window_ano = []
        for i in range(num_iters):
            ans = get_model_response(m)
            try:
                l = LLMresponse_to_list(ans, start, stop)
            except ValueError: 
                print(ans)
            window_ano.append(l)
            
        #Get final anomaly prediction
        final_ano = get_final_anomalous_list(window_ano, threshold = threshold)
        
        #Convert indices to timestamps
        t = indices_to_timestamp(signal, final_ano)
        combine_res.append(t)
    return combine_res

def rolling_filter_prediction(res, size, step): 
    """
    Get the final list of anomalous indices from results of rolling windows
    
    Args: 
        res (list of lists): result from rolling_LLM_prediction func
        size
        step
    Returns: 
        List of anomalous indices of the entire sequence.
    """
    raise NotImplementedError
    
