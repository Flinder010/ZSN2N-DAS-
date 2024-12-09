from obspy import read
import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.optim as optim
import torch.nn.functional as F
import torch.nn as nn
from sklearn import preprocessing
from scipy.signal import butter, filtfilt
from scipy.signal import find_peaks
import matplotlib.patches as patches
from matplotlib.patches import Patch

class network(nn.Module):
    def __init__(self,n_chan,chan_embed=48):
        super(network, self).__init__()

        self.act = nn.LeakyReLU(negative_slope=0.2, inplace=True)
        self.conv1 = nn.Conv2d(n_chan,chan_embed,3,padding=1)
        self.conv2 = nn.Conv2d(chan_embed, chan_embed, 3, padding = 1)
        self.conv3 = nn.Conv2d(chan_embed, n_chan, 1)

    def forward(self, x):
        x = self.act(self.conv1(x))
        x = self.act(self.conv2(x))
        x = self.conv3(x)

        return x

def pair_downsampler(img):
    c = img.shape[1]

    filter1 = torch.FloatTensor([[[[0 ,0.5],[0.5, 0]]]]).to(img.device)
    filter1 = filter1.repeat(c,1, 1, 1)

    filter2 = torch.FloatTensor([[[[0.5,0],[0, 0.5]]]]).to(img.device)
    filter2 = filter2.repeat(c,1, 1, 1)

    output1 = F.conv2d(img, filter1, stride=2, groups=c)
    output2 = F.conv2d(img, filter2, stride=2, groups=c)

    return output1, output2

def mse(gt: torch.Tensor, pred:torch.Tensor)-> torch.Tensor:
    loss = torch.nn.MSELoss()
    return loss(gt,pred)

def loss_func(noisy_img):
    noisy1, noisy2 = pair_downsampler(noisy_img)

    pred1 =  noisy1 - model(noisy1)
    pred2 =  noisy2 - model(noisy2)

    loss_res = 1/2*(mse(noisy1,pred2)+mse(noisy2,pred1))

    noisy_denoised =  noisy_img - model(noisy_img)
    denoised1, denoised2 = pair_downsampler(noisy_denoised)

    loss_cons=1/2*(mse(pred1,denoised1) + mse(pred2,denoised2))

    loss = loss_res + loss_cons

    print(loss)

    return loss

def train(model, optimizer, noisy_img):

  loss = loss_func(noisy_img)

  optimizer.zero_grad()
  loss.backward()
  optimizer.step()

  return loss.item()

def denoise(model, noisy_img):

    with torch.no_grad():
            pred = torch.clamp( noisy_img - model(noisy_img), -40, 40 )
    return pred

def butter_bandpass(lowcut, highcut, fs, order=5):  
    nyquist = 0.5 * fs  
    low = lowcut / nyquist  
    high = highcut / nyquist  
    b, a = butter(order, [low, high], btype='band')  
    return b, a 

def bandpass_filter(data, lowcut, highcut, fs, order=5):  
    b, a = butter_bandpass(lowcut, highcut, fs, order=order)  
    y = filtfilt(b, a, data, axis=0)  # setting axis = 0 represents filtering each column
    return y 

def apply_border_division(matrix, border_size1, border_size2):   
    rows, cols = matrix.shape   
    processed_matrix = matrix.copy()  
    processed_matrix[:border_size1, border_size2:-border_size2] /= 10 
    processed_matrix[-border_size1:, border_size2:-border_size2] /= 10  
    return processed_matrix  

def count_parameters(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)

example1 = "D:\Data\DAS-N2N-main\data\\BPT1_UTC_20200117_044207.903.mseed"
st_raw = read(example1)  

st_raw_array = np.zeros((st_raw[0].stats.npts, len(st_raw)))  #(2048,986)
for tr_no in range(len(st_raw)):
    st_raw_array[:,tr_no] = st_raw[tr_no].data

st_raw_array_resize = st_raw_array[:1000,:]
matrix = st_raw_array_resize

column_averages = np.mean(matrix, axis=0)
matrix_std = np.std(matrix, axis=0)
standard_matrix = (matrix - column_averages) / matrix_std

fs = 1000
lowcut = 30.0  
highcut = 100.0 
filtered_matrix = bandpass_filter(standard_matrix, lowcut, highcut, fs)
threshold = np.std(filtered_matrix) * 1.5
filtered_matrix[np.abs(filtered_matrix) < threshold] /= 15

border_size1 = 20 
border_size2 = 50
filtered_matrix = apply_border_division(filtered_matrix, border_size1, border_size2)

filtered_matrix = filtered_matrix.copy()
resize_image = torch.from_numpy(filtered_matrix).float()[None, None, :, :]  

n_chan = resize_image.shape[1]
model = network(n_chan)

#print(count_parameters(model))

max_epoch = 0
lr = 0.001        
step_size = 1000     
gamma = 0.5
i = 0          

model = torch.load("D:\PythonCode\Denoise\\Test_Generalized\\test2_model.pt")
optimizer = optim.Adam(model.parameters(), lr=lr)
scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=step_size, gamma=gamma)

for epoch in range(max_epoch):
    train(model, optimizer, resize_image)
    scheduler.step()
    i+=1
    print(i)

denoised_img = denoise(model, resize_image)
#torch.save(model,'save_model.pt')

origin = resize_image.cpu().squeeze(0).permute(1,2,0)
denoised = denoised_img.cpu().squeeze(0).permute(1,2,0)
matrix_return = np.squeeze(denoised, axis=2) 
denoised_return = matrix_return * matrix_std

matrix = denoised_return

sta_n = int(0.01 * matrix.shape[0])
lta_n = int(0.1 * matrix.shape[0])
threshold = 4

result = np.zeros_like(matrix, dtype=int)
 
for col in range(matrix.shape[1]):
    signal = matrix[:, col]
    sta = np.convolve(np.abs(signal), np.ones(sta_n) / sta_n, mode='same')
    lta = np.convolve(np.abs(signal), np.ones(lta_n) / lta_n, mode='same')
    lta[lta == 0] = np.finfo(float).eps
    sta_lta_ratio = sta / lta
    peaks, _ = find_peaks(sta_lta_ratio, height=threshold)
    result[peaks, col] = 1

rows_to_check1 = result[380:420, :]
rows_to_check2 = result[600:640, :]
rows_to_check3 = result[920:960, :]
count_of_arrivals1 = np.sum(rows_to_check1 == 1)
count_of_arrivals2 = np.sum(rows_to_check2 == 1)
count_of_arrivals3 = np.sum(rows_to_check3 == 1)

plt.rcParams["figure.figsize"] = (9,9)
fig, ax = plt.subplots()

im = ax.imshow(result, vmin=-1, vmax=1, cmap="seismic", aspect="auto", extent=[0,len(st_raw),1,0])

rect1 = patches.Rectangle((100, 0.260), 550, 0.125, linewidth=4, edgecolor='r', facecolor='none')
rect2 = patches.Rectangle((100, 0.525), 550, 0.105, linewidth=4, edgecolor='m', facecolor='none')
rect3 = patches.Rectangle((100, 0.850), 550, 0.105, linewidth=4, edgecolor='b', facecolor='none')

ax.add_patch(rect1)
ax.add_patch(rect2)
ax.add_patch(rect3)
ax.legend(handles=[Patch(facecolor='none', edgecolor='r', linewidth=2,label='Arrivals in box = ' + format(count_of_arrivals1)),
                   Patch(facecolor='none', edgecolor='m', linewidth=2,label='Arrivals in box = ' + format(count_of_arrivals2)),
                   Patch(facecolor='none', edgecolor='b', linewidth=2,label='Arrivals in box = ' + format(count_of_arrivals3))], 
                   prop={'size': 20})

plt.xlabel('DAS channel', fontsize=20)
plt.ylabel('Time(s)', fontsize=20)
plt.xticks(fontsize=20)
plt.yticks(fontsize=20)

fig.suptitle("(f)ZSN2N-DAS", fontsize=28) 

plt.show()